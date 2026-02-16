"""Tests for WebChannel server lifecycle."""

from __future__ import annotations

import pytest

from openhydra.channels.base import Channel
from openhydra.channels.web.server import WebChannel
from openhydra.config import WebConfig
from openhydra.events import EventBus


class FakeEngine:
    """Minimal engine for server tests."""

    def __init__(self):
        self.events = EventBus()


def test_web_channel_satisfies_protocol():
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig())
    assert isinstance(ch, Channel)


def test_web_channel_name():
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig())
    assert ch.name == "web"


def test_build_app_creates_starlette():
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig())
    app = ch._build_app()
    assert app is not None


def test_build_app_with_api_key():
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig(api_key="secret"))
    app = ch._build_app()
    # Middleware is added
    assert app is not None


def test_app_property_none_before_start():
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig())
    assert ch.app is None


@pytest.mark.asyncio
async def test_stop_without_start():
    """stop() is safe to call even if never started."""
    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig())
    await ch.stop()  # Should not raise
