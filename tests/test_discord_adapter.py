"""Tests for Discord adapter lifecycle and handlers (mocked discord.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.channels.access import AccessControl
from openhydra.channels.base import Channel
from openhydra.channels.context import ChannelContext
from openhydra.channels.discord.handlers import DiscordHandlers
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
        self.get_status = AsyncMock(return_value={"id": "wf-123", "status": "running"})
        self.list_workflows = AsyncMock(return_value=[])


def _make_interaction(user_id="12345"):
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = int(user_id)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.channel_id = 12345
    followup_msg = MagicMock()
    followup_msg.id = 999
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value=followup_msg)
    return interaction


@pytest.fixture
def engine():
    return FakeEngine()


class FakeClient:
    """Minimal mock of discord.Client."""

    def __init__(self):
        self._event_handlers = {}
        self.get_channel = MagicMock(return_value=None)

    def event(self, func):
        self._event_handlers[func.__name__] = func
        return func


@pytest.fixture
def client():
    return FakeClient()


def _ctx(engine=None):
    return ChannelContext(engine=engine or FakeEngine())


@pytest.fixture
def handlers(client, engine):
    h = DiscordHandlers(client, _ctx(engine), AccessControl())
    return h


def test_discord_channel_protocol_conformance():
    from openhydra.channels.context import ChannelContext
    from openhydra.channels.discord.adapter import DiscordChannel
    from openhydra.config import DiscordConfig

    ctx = ChannelContext(engine=FakeEngine())
    ch = DiscordChannel(DiscordConfig(), ctx)
    assert isinstance(ch, Channel)


def test_discord_channel_name():
    from openhydra.channels.context import ChannelContext
    from openhydra.channels.discord.adapter import DiscordChannel
    from openhydra.config import DiscordConfig

    ctx = ChannelContext(engine=FakeEngine())
    ch = DiscordChannel(DiscordConfig(), ctx)
    assert ch.name == "discord"


@pytest.mark.asyncio
async def test_handle_run_command(engine):
    """The run action calls engine.submit."""
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "run", "build a thing")

    interaction.response.defer.assert_called_once()
    engine.submit.assert_called_once_with(
        "build a thing",
        session_key="discord:12345",
        channel="discord",
        user_id="12345",
    )
    interaction.followup.send.assert_called_once()


@pytest.mark.asyncio
async def test_handle_run_empty_argument(engine):
    """Empty task description prompts the user."""
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "run", "")

    engine.submit.assert_not_called()
    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_handle_approve_command(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "approve", "ap-1")

    engine.approve.assert_called_once_with("ap-1")


@pytest.mark.asyncio
async def test_handle_reject_command(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "reject", "ap-1")

    engine.reject.assert_called_once_with("ap-1", "Rejected via Discord")


@pytest.mark.asyncio
async def test_handle_unknown_action(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "foobar", "")

    interaction.response.send_message.assert_called_once()
    assert "unknown" in interaction.response.send_message.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_button_approve(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await h._handle_button(interaction, "approve:ap-42")

    engine.approve.assert_called_once_with("ap-42")


@pytest.mark.asyncio
async def test_button_reject(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await h._handle_button(interaction, "reject:ap-42")

    engine.reject.assert_called_once_with("ap-42", "Rejected via Discord")


@pytest.mark.asyncio
async def test_engine_event_ignored_without_thread(engine):
    """Events for untracked workflows are silently ignored."""
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    event = Event(type="step.completed", data={"workflow_id": "wf-unknown"})
    await h.on_engine_event(event)

    # No error, no call
    client.get_channel.assert_not_called()


@pytest.mark.asyncio
async def test_engine_event_cleanup_on_completion(engine):
    """Thread mapping is cleaned up when workflow completes."""
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())
    h._threads["wf-123"] = (1, 2)

    event = Event(type="workflow.completed", data={"workflow_id": "wf-123"})
    await h.on_engine_event(event)

    assert "wf-123" not in h._threads


@pytest.mark.asyncio
async def test_handle_pause_command(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "pause", "wf-123")

    engine.pause.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_handle_resume_command(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "resume", "wf-123")

    engine.resume.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_handle_cancel_command(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = _make_interaction()
    await h._handle_command(interaction, "cancel", "wf-123")

    engine.cancel.assert_called_once_with("wf-123")


@pytest.mark.asyncio
async def test_button_pause(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await h._handle_button(interaction, "pause:wf-42")
    engine.pause.assert_called_once_with("wf-42")


@pytest.mark.asyncio
async def test_button_resume(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await h._handle_button(interaction, "resume:wf-42")
    engine.resume.assert_called_once_with("wf-42")


@pytest.mark.asyncio
async def test_button_cancel(engine):
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await h._handle_button(interaction, "cancel:wf-42")
    engine.cancel.assert_called_once_with("wf-42")


@pytest.mark.asyncio
async def test_engine_event_cleanup_on_cancel(engine):
    """Thread mapping is cleaned up when workflow is cancelled."""
    client = FakeClient()
    h = DiscordHandlers(client, _ctx(engine), AccessControl())
    h._threads["wf-123"] = (1, 2)

    event = Event(type="workflow.cancelled", data={"workflow_id": "wf-123"})
    await h.on_engine_event(event)

    assert "wf-123" not in h._threads


@pytest.mark.asyncio
async def test_stop_without_start():
    from openhydra.channels.context import ChannelContext
    from openhydra.channels.discord.adapter import DiscordChannel
    from openhydra.config import DiscordConfig

    ctx = ChannelContext(engine=FakeEngine())
    ch = DiscordChannel(DiscordConfig(), ctx)
    await ch.stop()  # Should not raise
