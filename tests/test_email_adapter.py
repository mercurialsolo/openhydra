"""Tests for email adapter lifecycle, protocol conformance, OAuth2, and factory."""

from __future__ import annotations

import dataclasses
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openhydra.channels.email import create_channel
from openhydra.channels.email.adapter import _TOKEN_EXPIRY_BUFFER, EmailChannel
from openhydra.channels.context import ChannelContext
from openhydra.config import EmailConfig
from openhydra.events import EventBus


@pytest.fixture
def email_config():
    return EmailConfig(
        enabled=True,
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="secret",
        poll_interval_seconds=30.0,
        mailbox="INBOX",
    )


@pytest.fixture
def oauth_config():
    return EmailConfig(
        enabled=True,
        imap_host="imap.gmail.com",
        imap_port=993,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="user@gmail.com",
        auth_method="oauth2",
        oauth_client_id="client-id-123",
        oauth_client_secret="client-secret-456",
        oauth_refresh_token="refresh-token-789",
        oauth_token_uri="https://oauth2.googleapis.com/token",
        poll_interval_seconds=30.0,
        mailbox="INBOX",
    )


@pytest.fixture
def ctx():
    class FakeEngine:
        def __init__(self):
            self.events = EventBus()
            self.submit = AsyncMock(return_value="wf-email-1")

    return ChannelContext(engine=FakeEngine())


class TestEmailChannelProtocol:
    def test_name(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)
        assert ch.name == "email"

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)
        await ch.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_start_without_imap_host(self, ctx):
        cfg = EmailConfig(enabled=True, imap_host="", username="")
        ch = EmailChannel(cfg, ctx)
        await ch.start()
        assert ch._task is None  # Should not start without config

    @pytest.mark.asyncio
    async def test_send_message_without_smtp(self, ctx):
        cfg = EmailConfig(enabled=True, smtp_host="")
        ch = EmailChannel(cfg, ctx)
        # Should not raise even without SMTP configured
        await ch.send_message("user@example.com", "Hello")


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_actionable_email_submitted(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)

        raw = (
            b"From: boss@company.com\r\n"
            b"Subject: Please review\r\n"
            b"Message-ID: <abc123@example.com>\r\n"
            b"\r\n"
            b"Can you check this?"
        )
        await ch._process_message(raw)
        ctx.engine.submit.assert_called_once()
        call_args = ctx.engine.submit.call_args[0][0]
        assert "boss@company.com" in call_args
        assert "Please review" in call_args

    @pytest.mark.asyncio
    async def test_spam_email_skipped(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)

        raw = (
            b"From: scam@evil.com\r\n"
            b"Subject: You won the lottery!\r\n"
            b"\r\n"
            b"Congratulations winner!"
        )
        await ch._process_message(raw)
        ctx.engine.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_fyi_email_skipped(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)

        raw = (
            b"From: noreply@github.com\r\n"
            b"Subject: New commit pushed\r\n"
            b"\r\n"
            b"Someone pushed a commit."
        )
        await ch._process_message(raw)
        ctx.engine.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_map_populated(self, email_config, ctx):
        ch = EmailChannel(email_config, ctx)

        raw = (
            b"From: user@example.com\r\n"
            b"Subject: Help me\r\n"
            b"Message-ID: <msg-42@example.com>\r\n"
            b"\r\n"
            b"I need assistance"
        )
        await ch._process_message(raw)
        assert "wf-email-1" in ch._thread_map
        assert ch._thread_map["wf-email-1"] == "<msg-42@example.com>"

    @pytest.mark.asyncio
    async def test_allowed_senders_filter(self, ctx):
        cfg = EmailConfig(
            enabled=True,
            imap_host="imap.example.com",
            username="user@example.com",
            password="secret",
            allowed_senders=["trusted@good.com"],
        )
        ch = EmailChannel(cfg, ctx)

        raw = (
            b"From: untrusted@bad.com\r\n"
            b"Subject: Hello\r\n"
            b"\r\n"
            b"Normal email content"
        )
        await ch._process_message(raw)
        ctx.engine.submit.assert_not_called()


class TestOAuth2Config:
    def test_default_auth_method_is_password(self):
        cfg = EmailConfig()
        assert cfg.auth_method == "password"

    def test_oauth2_config_fields(self, oauth_config):
        assert oauth_config.auth_method == "oauth2"
        assert oauth_config.oauth_client_id == "client-id-123"
        assert oauth_config.oauth_client_secret == "client-secret-456"
        assert oauth_config.oauth_refresh_token == "refresh-token-789"
        assert "googleapis.com" in oauth_config.oauth_token_uri

    def test_outlook_token_uri(self):
        cfg = EmailConfig(
            auth_method="oauth2",
            oauth_token_uri="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        )
        assert "microsoftonline.com" in cfg.oauth_token_uri


class TestOAuth2TokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_access_token(self, oauth_config, ctx):
        ch = EmailChannel(oauth_config, ctx)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "fresh-token-abc",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("openhydra.channels.email.adapter._httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            token = await ch._refresh_access_token()

        assert token == "fresh-token-abc"
        assert ch._access_token == "fresh-token-abc"
        assert ch._token_expires_at > 0

        # Verify correct POST data
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://oauth2.googleapis.com/token"
        post_data = call_args[1]["data"]
        assert post_data["client_id"] == "client-id-123"
        assert post_data["grant_type"] == "refresh_token"

    @pytest.mark.asyncio
    async def test_get_access_token_cached(self, oauth_config, ctx):
        ch = EmailChannel(oauth_config, ctx)
        ch._access_token = "cached-token"
        ch._token_expires_at = time.monotonic() + 3600  # Far in the future

        token = await ch._get_access_token()
        assert token == "cached-token"

    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_when_expired(self, oauth_config, ctx):
        ch = EmailChannel(oauth_config, ctx)
        ch._access_token = "expired-token"
        ch._token_expires_at = time.monotonic() - 100  # Already expired

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("openhydra.channels.email.adapter._httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            token = await ch._get_access_token()

        assert token == "new-token"

    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_within_buffer(self, oauth_config, ctx):
        ch = EmailChannel(oauth_config, ctx)
        ch._access_token = "almost-expired"
        # Will expire within buffer window
        ch._token_expires_at = time.monotonic() + (_TOKEN_EXPIRY_BUFFER - 10)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("openhydra.channels.email.adapter._httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            token = await ch._get_access_token()

        assert token == "refreshed-token"


class TestOAuth2AuthBranching:
    @pytest.mark.asyncio
    async def test_imap_uses_xoauth2(self, oauth_config, ctx):
        """Verify IMAP login branches to xoauth2 for oauth2 auth_method."""
        ch = EmailChannel(oauth_config, ctx)
        ch._access_token = "test-token"
        ch._token_expires_at = time.monotonic() + 3600

        mock_imap = MagicMock()
        mock_imap.wait_hello_from_server = AsyncMock()
        mock_imap.xoauth2 = AsyncMock()
        mock_imap.login = AsyncMock()
        mock_imap.select = AsyncMock()
        mock_imap.search = AsyncMock(return_value=("OK", [b""]))
        mock_imap.logout = AsyncMock()

        with patch("openhydra.channels.email.adapter._aioimaplib") as mock_lib:
            mock_lib.IMAP4_SSL.return_value = mock_imap
            await ch._poll_inbox()

        mock_imap.xoauth2.assert_called_once_with("user@gmail.com", "test-token")
        mock_imap.login.assert_not_called()

    @pytest.mark.asyncio
    async def test_imap_uses_password(self, email_config, ctx):
        """Verify IMAP login uses password for password auth_method."""
        ch = EmailChannel(email_config, ctx)

        mock_imap = MagicMock()
        mock_imap.wait_hello_from_server = AsyncMock()
        mock_imap.xoauth2 = AsyncMock()
        mock_imap.login = AsyncMock()
        mock_imap.select = AsyncMock()
        mock_imap.search = AsyncMock(return_value=("OK", [b""]))
        mock_imap.logout = AsyncMock()

        with patch("openhydra.channels.email.adapter._aioimaplib") as mock_lib:
            mock_lib.IMAP4_SSL.return_value = mock_imap
            await ch._poll_inbox()

        mock_imap.login.assert_called_once_with("user@example.com", "secret")
        mock_imap.xoauth2.assert_not_called()

    @pytest.mark.asyncio
    async def test_smtp_oauth2_sends_xoauth2(self, oauth_config, ctx):
        """Verify SMTP uses XOAUTH2 SASL for oauth2 auth_method."""
        ch = EmailChannel(oauth_config, ctx)
        ch._access_token = "smtp-token"
        ch._token_expires_at = time.monotonic() + 3600

        mock_smtp = MagicMock()
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.auth = AsyncMock()
        mock_smtp.send_message = AsyncMock()
        mock_smtp.quit = AsyncMock()

        with patch("openhydra.channels.email.adapter._aiosmtplib") as mock_lib:
            mock_lib.SMTP.return_value = mock_smtp
            await ch.send_message("to@example.com", "Hello")

        mock_smtp.auth.assert_called_once()
        auth_args = mock_smtp.auth.call_args[0]
        assert auth_args[0] == "XOAUTH2"
        assert "user=user@gmail.com" in auth_args[1]
        assert "auth=Bearer smtp-token" in auth_args[1]


class TestFactory:
    def test_create_channel(self, email_config, ctx):
        config_dict = dataclasses.asdict(email_config)
        ch = create_channel(config_dict, ctx)
        assert ch.name == "email"

    def test_create_channel_ignores_extra_keys(self, email_config, ctx):
        config_dict = dataclasses.asdict(email_config)
        config_dict["unknown_key"] = "value"
        ch = create_channel(config_dict, ctx)
        assert ch.name == "email"

    def test_create_channel_with_oauth_config(self, oauth_config, ctx):
        config_dict = dataclasses.asdict(oauth_config)
        ch = create_channel(config_dict, ctx)
        assert ch.name == "email"
        assert ch._config.auth_method == "oauth2"
