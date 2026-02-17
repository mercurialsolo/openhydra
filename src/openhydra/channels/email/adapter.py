"""EmailChannel — IMAP poll loop + SMTP send, follows Channel protocol."""

from __future__ import annotations

import asyncio
import email
import email.utils
import logging
import time
from email.message import EmailMessage
from typing import TYPE_CHECKING

from .classifier import EmailCategory, classify_email

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

try:
    import aioimaplib as _aioimaplib
except ImportError:
    _aioimaplib = None  # type: ignore[assignment]

try:
    import aiosmtplib as _aiosmtplib
except ImportError:
    _aiosmtplib = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from openhydra.channels.context import ChannelContext
    from openhydra.config import EmailConfig

logger = logging.getLogger(__name__)

# Refresh access tokens 5 minutes before they expire
_TOKEN_EXPIRY_BUFFER = 300


class EmailChannel:
    """Email channel using IMAP for inbound and SMTP for outbound."""

    def __init__(
        self,
        config: EmailConfig,
        ctx: ChannelContext,
    ) -> None:
        self._engine = ctx.engine
        self._config = config
        self._ctx = ctx
        self._task: asyncio.Task | None = None
        # Track message IDs for threading replies
        self._thread_map: dict[str, str] = {}  # workflow_id -> message_id
        # OAuth2 token cache
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    @property
    def name(self) -> str:
        return "email"

    async def start(self) -> None:
        """Start the IMAP poll loop."""
        if not self._config.imap_host or not self._config.username:
            logger.warning(
                "Email channel enabled but IMAP host or username not configured"
            )
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Email channel started (poll=%ds, mailbox=%s, auth=%s)",
            self._config.poll_interval_seconds,
            self._config.mailbox,
            self._config.auth_method,
        )

    async def stop(self) -> None:
        """Stop the poll loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Email channel stopped")

    async def send_message(self, user_id: str, text: str) -> None:
        """Send an email to a user (user_id = email address)."""
        await self._send_email(
            to_addr=user_id,
            subject="OpenHydra Update",
            body=text,
        )

    async def send_reply(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        references: str = "",
    ) -> None:
        """Send a reply email with proper threading headers."""
        await self._send_email(
            to_addr=to_addr,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
        )

    # --- OAuth2 token management ---

    async def _refresh_access_token(self) -> str:
        """Refresh the OAuth2 access token using the refresh token."""
        if _httpx is None:
            raise RuntimeError(
                "httpx is required for OAuth2 email auth. "
                "Install with: pip install httpx"
            )

        async with _httpx.AsyncClient() as client:
            resp = await client.post(
                self._config.oauth_token_uri,
                data={
                    "client_id": self._config.oauth_client_id,
                    "client_secret": self._config.oauth_client_secret,
                    "refresh_token": self._config.oauth_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in
        logger.debug("OAuth2 access token refreshed (expires_in=%ds)", expires_in)
        return self._access_token

    async def _get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        remaining = self._token_expires_at - _TOKEN_EXPIRY_BUFFER
        if self._access_token and time.monotonic() < remaining:
            return self._access_token
        return await self._refresh_access_token()

    # --- Poll loop ---

    async def _poll_loop(self) -> None:
        """Main poll loop — sleep then check inbox."""
        try:
            while True:
                try:
                    await self._poll_inbox()
                except Exception:
                    logger.exception("Email poll failed")
                await asyncio.sleep(self._config.poll_interval_seconds)
        except asyncio.CancelledError:
            return

    async def _poll_inbox(self) -> None:
        """Connect to IMAP, fetch unseen messages, process each."""
        if _aioimaplib is None:
            logger.warning(
                "aioimaplib not installed — email polling disabled. "
                "Install with: pip install aioimaplib"
            )
            return

        imap = _aioimaplib.IMAP4_SSL(
            host=self._config.imap_host,
            port=self._config.imap_port,
        )
        try:
            await imap.wait_hello_from_server()

            if self._config.auth_method == "oauth2":
                token = await self._get_access_token()
                await imap.xoauth2(self._config.username, token)
            else:
                await imap.login(self._config.username, self._config.password)

            await imap.select(self._config.mailbox)

            _, data = await imap.search("UNSEEN")
            if not data or not data[0]:
                return

            msg_nums = data[0].split()
            for num in msg_nums:
                try:
                    _, msg_data = await imap.fetch(num, "(RFC822)")
                    if msg_data and len(msg_data) >= 2:
                        raw = msg_data[1]
                        if isinstance(raw, tuple) and len(raw) >= 2:
                            raw = raw[1]
                        if isinstance(raw, bytes):
                            await self._process_message(raw)
                except Exception:
                    logger.exception("Failed to process email %s", num)
        finally:
            try:
                await imap.logout()
            except Exception:
                pass

    async def _process_message(self, raw: bytes) -> None:
        """Parse, classify, and submit actionable emails."""
        msg = email.message_from_bytes(raw)

        sender = msg.get("From", "")
        subject = msg.get("Subject", "")
        message_id = msg.get("Message-ID", "")

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        # Classify
        category = classify_email(
            sender=sender,
            subject=subject,
            body=body,
            allowed_senders=self._config.allowed_senders,
        )

        if category == EmailCategory.SPAM:
            logger.debug("Email from %s classified as SPAM, skipping", sender)
            return

        if category == EmailCategory.FYI:
            logger.debug("Email from %s classified as FYI, skipping", sender)
            return

        # Actionable — submit to engine
        task_text = (
            f"Email from {sender}\n"
            f"Subject: {subject}\n\n"
            f"{body[:2000]}"
        )

        try:
            workflow_id = await self._engine.submit(task_text)
            if message_id:
                self._thread_map[workflow_id] = message_id
            logger.info(
                "Email from %s submitted as workflow %s",
                sender, workflow_id[:8],
            )
        except Exception:
            logger.exception("Failed to submit email from %s", sender)

    async def _send_email(
        self,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str = "",
        references: str = "",
    ) -> None:
        """Send an email via SMTP."""
        if _aiosmtplib is None:
            logger.warning(
                "aiosmtplib not installed — email sending disabled. "
                "Install with: pip install aiosmtplib"
            )
            return

        if not self._config.smtp_host:
            logger.warning("SMTP host not configured, cannot send email")
            return

        msg = EmailMessage()
        msg["From"] = self._config.username
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        try:
            if self._config.auth_method == "oauth2":
                await self._send_email_oauth2(msg)
            else:
                await _aiosmtplib.send(
                    msg,
                    hostname=self._config.smtp_host,
                    port=self._config.smtp_port,
                    username=self._config.username,
                    password=self._config.password,
                    start_tls=True,
                )
            logger.info("Email sent to %s: %s", to_addr, subject)
        except Exception:
            logger.exception("Failed to send email to %s", to_addr)

    async def _send_email_oauth2(self, msg: EmailMessage) -> None:
        """Send email via SMTP with XOAUTH2 SASL authentication."""
        token = await self._get_access_token()
        username = self._config.username
        sasl_string = f"user={username}\x01auth=Bearer {token}\x01\x01"

        smtp = _aiosmtplib.SMTP(
            hostname=self._config.smtp_host,
            port=self._config.smtp_port,
        )
        try:
            await smtp.connect()
            await smtp.starttls()
            await smtp.auth("XOAUTH2", sasl_string)
            await smtp.send_message(msg)
        finally:
            try:
                await smtp.quit()
            except Exception:
                pass
