"""Tests for ChannelContext dataclass and channel factory functions."""

from __future__ import annotations

from openhydra.channels.context import ChannelContext
from openhydra.events import EventBus


class FakeEngine:
    def __init__(self):
        self.events = EventBus()


def test_channel_context_minimal():
    """ChannelContext can be created with just an engine."""
    ctx = ChannelContext(engine=FakeEngine())
    assert ctx.engine is not None
    assert ctx.sessions is None
    assert ctx.debouncer is None
    assert ctx.auth_store is None
    assert ctx.auth_manager is None


def test_channel_context_full():
    """ChannelContext accepts all optional services."""
    engine = FakeEngine()
    ctx = ChannelContext(
        engine=engine,
        sessions="fake-sessions",
        debouncer="fake-debouncer",
        auth_store="fake-store",
        auth_manager="fake-manager",
    )
    assert ctx.sessions == "fake-sessions"
    assert ctx.debouncer == "fake-debouncer"
    assert ctx.auth_store == "fake-store"
    assert ctx.auth_manager == "fake-manager"


# --- Factory function signatures ---


def test_web_factory_signature():
    from openhydra.channels.web import create_channel

    assert callable(create_channel)


def test_slack_factory_signature():
    from openhydra.channels.slack import create_channel

    assert callable(create_channel)


def test_discord_factory_signature():
    from openhydra.channels.discord import create_channel

    assert callable(create_channel)


def test_whatsapp_factory_signature():
    from openhydra.channels.whatsapp import create_channel

    assert callable(create_channel)


def test_web_factory_creates_channel():
    """Web factory returns a valid Channel instance."""
    from openhydra.channels.base import Channel
    from openhydra.channels.web import create_channel

    ctx = ChannelContext(engine=FakeEngine())
    ch = create_channel({"enabled": True, "host": "127.0.0.1", "port": 8080, "api_key": ""}, ctx)
    assert isinstance(ch, Channel)
    assert ch.name == "web"
