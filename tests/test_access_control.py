"""Tests for access control (allowlists) on channel handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.channels.slack.handlers import SlackHandlers
from openhydra.channels.whatsapp.handlers import WhatsAppHandlers
from openhydra.config import WhatsAppConfig
from openhydra.events import EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-123")
        self.approve = AsyncMock()
        self.reject = AsyncMock()


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
    h = SlackHandlers(bolt, engine, allowed_users=[])
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "anyone"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_slack_allowlist_blocks_unauthorized():
    engine = FakeEngine()
    bolt = FakeBoltApp()
    h = SlackHandlers(bolt, engine, allowed_users=["U-allowed"])
    h.register()

    say = AsyncMock()
    event = {"text": "hello", "channel": "C1", "ts": "1", "user": "U-blocked"}
    await bolt._event_handlers["app_mention"][0](event=event, say=say)
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_slack_allowlist_permits_authorized():
    engine = FakeEngine()
    bolt = FakeBoltApp()
    h = SlackHandlers(bolt, engine, allowed_users=["U-allowed"])
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
    h = WhatsAppHandlers(engine, config, bridge=bridge)

    await h.on_message("+1111", "hello")
    engine.submit.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_allowlist_blocks_unauthorized():
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=["+9999"])
    bridge = MagicMock()
    bridge.send = AsyncMock()
    h = WhatsAppHandlers(engine, config, bridge=bridge)

    await h.on_message("+1111", "hello")
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_allowlist_permits_authorized():
    engine = FakeEngine()
    config = WhatsAppConfig(allowed_phones=["+9999"])
    bridge = MagicMock()
    bridge.send = AsyncMock()
    h = WhatsAppHandlers(engine, config, bridge=bridge)

    await h.on_message("+9999", "hello")
    engine.submit.assert_called_once()
