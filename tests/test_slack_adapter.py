"""Tests for Slack adapter lifecycle and handler dispatch (mocked Slack API)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.channels.access import AccessControl
from openhydra.channels.base import Channel
from openhydra.channels.context import ChannelContext
from openhydra.channels.slack.handlers import SlackHandlers
from openhydra.events import Event, EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-123")
        self.approve = AsyncMock()
        self.reject = AsyncMock()
        self.pause = AsyncMock()
        self.resume = AsyncMock(return_value="wf-123")
        self.cancel = AsyncMock()


class FakeBoltApp:
    """Minimal mock of slack_bolt AsyncApp for handler registration."""

    def __init__(self):
        self._event_handlers: dict[str, list] = {}
        self._action_handlers: dict[str, list] = {}
        self.client = MagicMock()
        self.client.chat_postMessage = AsyncMock()

    def event(self, event_type: str):
        def decorator(func):
            self._event_handlers.setdefault(event_type, []).append(func)
            return func
        return decorator

    def action(self, action_id: str):
        def decorator(func):
            self._action_handlers.setdefault(action_id, []).append(func)
            return func
        return decorator


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def bolt_app():
    return FakeBoltApp()


def _ctx(engine=None):
    return ChannelContext(engine=engine or FakeEngine())


@pytest.fixture
def handlers(bolt_app, engine):
    h = SlackHandlers(bolt_app, _ctx(engine), AccessControl())
    h.register()
    return h


def test_handlers_register_events(bolt_app, handlers):
    assert "app_mention" in bolt_app._event_handlers
    assert "message" in bolt_app._event_handlers


def test_handlers_register_actions(bolt_app, handlers):
    assert "approve" in bolt_app._action_handlers
    assert "reject" in bolt_app._action_handlers


@pytest.mark.asyncio
async def test_mention_submits_task(bolt_app, handlers, engine):
    say = AsyncMock()
    event = {"text": "<@U123> build a thing", "channel": "C1", "ts": "1234.5", "user": "U1"}
    handler_fn = bolt_app._event_handlers["app_mention"][0]
    await handler_fn(event=event, say=say)

    engine.submit.assert_called_once_with("build a thing")
    say.assert_called_once()
    assert "wf-123" in say.call_args[1].get(
        "text", say.call_args[0][0] if say.call_args[0] else ""
    )


@pytest.mark.asyncio
async def test_dm_submits_task(bolt_app, handlers, engine):
    say = AsyncMock()
    event = {"text": "hello task", "channel": "D1", "ts": "1", "channel_type": "im", "user": "U1"}
    handler_fn = bolt_app._event_handlers["message"][0]
    await handler_fn(event=event, say=say)

    engine.submit.assert_called_once_with("hello task")


@pytest.mark.asyncio
async def test_dm_ignores_subtypes(bolt_app, handlers, engine):
    say = AsyncMock()
    event = {"text": "edited", "channel_type": "im", "subtype": "message_changed"}
    handler_fn = bolt_app._event_handlers["message"][0]
    await handler_fn(event=event, say=say)

    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_empty_mention_asks_for_task(bolt_app, handlers, engine):
    say = AsyncMock()
    event = {"text": "<@U123>", "channel": "C1", "ts": "1", "user": "U1"}
    handler_fn = bolt_app._event_handlers["app_mention"][0]
    await handler_fn(event=event, say=say)

    engine.submit.assert_not_called()
    say.assert_called_once()
    assert "task" in say.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_approve_action(bolt_app, handlers, engine):
    ack = AsyncMock()
    say = AsyncMock()
    action = {"value": "ap-99"}
    handler_fn = bolt_app._action_handlers["approve"][0]
    await handler_fn(ack=ack, action=action, say=say)

    ack.assert_called_once()
    engine.approve.assert_called_once_with("ap-99")


@pytest.mark.asyncio
async def test_reject_action(bolt_app, handlers, engine):
    ack = AsyncMock()
    say = AsyncMock()
    action = {"value": "ap-99"}
    handler_fn = bolt_app._action_handlers["reject"][0]
    await handler_fn(ack=ack, action=action, say=say)

    ack.assert_called_once()
    engine.reject.assert_called_once_with("ap-99", "Rejected via Slack")


@pytest.mark.asyncio
async def test_engine_event_forwarded_to_thread(bolt_app, handlers):
    """Engine events are posted as threaded replies."""
    # Simulate a tracked thread
    handlers._threads["wf-123"] = ("C1", "1234.5")

    event = Event(type="step.completed", data={"workflow_id": "wf-123", "role_id": "eng"})
    await handlers.on_engine_event(event)

    bolt_app.client.chat_postMessage.assert_called_once()
    call_kwargs = bolt_app.client.chat_postMessage.call_args[1]
    assert call_kwargs["channel"] == "C1"
    assert call_kwargs["thread_ts"] == "1234.5"


@pytest.mark.asyncio
async def test_engine_event_cleanup_on_completion(bolt_app, handlers):
    """Thread mapping is cleaned up when workflow completes."""
    handlers._threads["wf-123"] = ("C1", "1234.5")

    event = Event(type="workflow.completed", data={"workflow_id": "wf-123"})
    await handlers.on_engine_event(event)

    assert "wf-123" not in handlers._threads


@pytest.mark.asyncio
async def test_engine_event_ignored_for_unknown_workflow(bolt_app, handlers):
    """Events for untracked workflows are silently ignored."""
    event = Event(type="step.completed", data={"workflow_id": "wf-unknown"})
    await handlers.on_engine_event(event)

    bolt_app.client.chat_postMessage.assert_not_called()


def test_handlers_register_lifecycle_actions(bolt_app, handlers):
    assert "pause_wf" in bolt_app._action_handlers
    assert "resume_wf" in bolt_app._action_handlers
    assert "cancel_wf" in bolt_app._action_handlers


@pytest.mark.asyncio
async def test_pause_action(bolt_app, handlers, engine):
    ack = AsyncMock()
    say = AsyncMock()
    action = {"value": "wf-123"}
    handler_fn = bolt_app._action_handlers["pause_wf"][0]
    await handler_fn(ack=ack, action=action, say=say)

    ack.assert_called_once()
    engine.pause.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_resume_action(bolt_app, handlers, engine):
    ack = AsyncMock()
    say = AsyncMock()
    action = {"value": "wf-123"}
    handler_fn = bolt_app._action_handlers["resume_wf"][0]
    await handler_fn(ack=ack, action=action, say=say)

    ack.assert_called_once()
    engine.resume.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_cancel_action(bolt_app, handlers, engine):
    ack = AsyncMock()
    say = AsyncMock()
    action = {"value": "wf-123"}
    handler_fn = bolt_app._action_handlers["cancel_wf"][0]
    await handler_fn(ack=ack, action=action, say=say)

    ack.assert_called_once()
    engine.cancel.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_engine_event_cleanup_on_cancel(bolt_app, handlers):
    """Thread mapping is cleaned up when workflow is cancelled."""
    handlers._threads["wf-123"] = ("C1", "1234.5")

    event = Event(type="workflow.cancelled", data={"workflow_id": "wf-123"})
    await handlers.on_engine_event(event)

    assert "wf-123" not in handlers._threads


def test_slack_channel_protocol_conformance():
    """SlackChannel class satisfies Channel protocol (structural check)."""
    # Can't instantiate without slack-bolt, but we can check the class itself
    from openhydra.channels.slack.adapter import SlackChannel

    assert hasattr(SlackChannel, "name")
    assert hasattr(SlackChannel, "start")
    assert hasattr(SlackChannel, "stop")
    assert hasattr(SlackChannel, "send_message")

    from openhydra.channels.context import ChannelContext
    from openhydra.config import SlackConfig

    ctx = ChannelContext(engine=FakeEngine())
    ch = SlackChannel(SlackConfig(), ctx)
    assert isinstance(ch, Channel)
