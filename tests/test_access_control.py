"""Tests for access control (allowlists + auth store) on channel handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.channels.access import AccessControl
from openhydra.channels.auth.manager import AuthManager
from openhydra.channels.auth.store import AuthStore
from openhydra.channels.context import ChannelContext
from openhydra.channels.slack.handlers import SlackHandlers
from openhydra.channels.whatsapp.handlers import WhatsAppHandlers
from openhydra.config import WhatsAppConfig
from openhydra.db import Database
from openhydra.events import EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-123")
        self.approve = AsyncMock()
        self.reject = AsyncMock()


def _ctx(engine=None):
    return ChannelContext(engine=engine or FakeEngine())


class FakeBoltApp:
    def __init__(self):
        self._event_handlers = {}
        self._action_handlers = {}
        self.client = MagicMock()
        self.client.chat_postMessage = AsyncMock()

    def event(self, event_type):
        def decorator(func):
            self._event_handlers.setdefault(event_type, []).append(func)
            return func
        return decorator

    def action(self, action_id):
        def decorator(func):
            self._action_handlers.setdefault(action_id, []).append(func)
            return func
        return decorator


# --- Slack ---


@pytest.mark.asyncio
async def test_slack_empty_allowlist_allows_all():
    engine = FakeEngine()
    bolt = FakeBoltApp()
    access = AccessControl(allowed_ids=[])
    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "anyone"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_slack_allowlist_blocks_unauthorized():
    engine = FakeEngine()
    bolt = FakeBoltApp()
    access = AccessControl(allowed_ids=["U-allowed"])
    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-blocked"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_slack_allowlist_permits_authorized():
    engine = FakeEngine()
    bolt = FakeBoltApp()
    access = AccessControl(allowed_ids=["U-allowed"])
    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-allowed"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()


# --- WhatsApp ---


@pytest.mark.asyncio
async def test_whatsapp_empty_allowlist_allows_all():
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=[])
    bridge = MagicMock()
    bridge.send = AsyncMock()
    access = AccessControl(allowed_ids=[])
    h = WhatsAppHandlers(config, _ctx(engine), access, bridge=bridge)

    await h.on_message("+1111", "hello")
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_allowlist_blocks_unauthorized():
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=["+9999"])
    bridge = MagicMock()
    bridge.send = AsyncMock()
    access = AccessControl(allowed_ids=["+9999"])
    h = WhatsAppHandlers(config, _ctx(engine), access, bridge=bridge)

    await h.on_message("+1111", "hello")
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_allowlist_permits_authorized():
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=["+9999"])
    bridge = MagicMock()
    bridge.send = AsyncMock()
    access = AccessControl(allowed_ids=["+9999"])
    h = WhatsAppHandlers(config, _ctx(engine), access, bridge=bridge)

    await h.on_message("+9999", "hello")
    engine.submit.assert_called_once()


# --- Auth store integration ---


@pytest.fixture()
async def auth_db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_slack_auth_store_unknown_user_triggers_challenge(auth_db):
    """Unknown user with auth store triggers a challenge instead of silent drop."""
    engine = FakeEngine()
    bolt = FakeBoltApp()
    store = AuthStore(auth_db)
    manager = AuthManager(store, engine.events)
    access = AccessControl(auth_store=store, auth_manager=manager)

    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-unknown"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)

    engine.submit.assert_not_called()
    say.assert_called()  # Should notify user about auth


@pytest.mark.asyncio
async def test_slack_auth_store_authorized_user_passes(auth_db):
    """Authorized user in auth store should be allowed."""
    engine = FakeEngine()
    bolt = FakeBoltApp()
    store = AuthStore(auth_db)
    await store.authorize("slack", "U-auth")
    access = AccessControl(auth_store=store)

    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-auth"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_slack_config_allowlist_still_works(auth_db):
    """Config allowlist should still take priority over auth store."""
    engine = FakeEngine()
    bolt = FakeBoltApp()
    store = AuthStore(auth_db)
    access = AccessControl(allowed_ids=["U-config"], auth_store=store)

    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    # Allowed via config
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-config"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()

    # Blocked via config (even if auth store has them)
    engine.submit.reset_mock()
    event2 = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-other"}
    await bolt._event_handlers["app_mention"][0](event=event2, say=say)
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_slack_no_auth_store_allows_all():
    """No auth store + no allowlist → allow all."""
    engine = FakeEngine()
    bolt = FakeBoltApp()
    access = AccessControl()  # No allowlist, no auth store
    h = SlackHandlers(bolt, _ctx(engine), access)
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "anyone"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_auth_store_unknown_triggers_challenge(auth_db):
    """Unknown WhatsApp user triggers auth challenge."""
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=[])
    store = AuthStore(auth_db)
    manager = AuthManager(store, engine.events)
    bridge = MagicMock()
    bridge.send = AsyncMock()
    access = AccessControl(auth_store=store, auth_manager=manager)

    h = WhatsAppHandlers(config, _ctx(engine), access, bridge=bridge)

    await h.on_message("+1111", "hello")
    engine.submit.assert_not_called()
    bridge.send.assert_called()  # Should notify about auth
