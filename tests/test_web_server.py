"""Tests for WebChannel server lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from openhydra.channels.base import Channel
from openhydra.channels.context import ChannelContext
from openhydra.channels.web.server import WebChannel
from openhydra.config import WebConfig
from openhydra.events import EventBus


class FakeEngine:
    """Minimal engine for server tests."""

    def __init__(self):
        self.events = EventBus()
        self.pause = AsyncMock()
        self.resume = AsyncMock(return_value="wf-123")
        self.cancel = AsyncMock()


def _ctx(engine=None):
    return ChannelContext(engine=engine or FakeEngine())


def test_web_channel_satisfies_protocol():
    ch = WebChannel(WebConfig(), _ctx())
    assert isinstance(ch, Channel)


def test_web_channel_name():
    ch = WebChannel(WebConfig(), _ctx())
    assert ch.name == "web"


def test_build_app_creates_starlette():
    ch = WebChannel(WebConfig(), _ctx())
    app = ch._build_app()
    assert app is not None


def test_build_app_with_api_key():
    ch = WebChannel(WebConfig(api_key="secret"), _ctx())
    app = ch._build_app()
    # Middleware is added
    assert app is not None


def test_app_property_none_before_start():
    ch = WebChannel(WebConfig(), _ctx())
    assert ch.app is None


@pytest.mark.asyncio
async def test_stop_without_start():
    """stop() is safe to call even if never started."""
    ch = WebChannel(WebConfig(), _ctx())
    await ch.stop()  # Should not raise


# --- REST endpoint tests for pause/resume/cancel ---


def _make_test_client(engine=None) -> TestClient:
    from openhydra.channels.web.routes import build_routes

    eng = engine or FakeEngine()
    routes = build_routes(eng)
    app = Starlette(routes=routes)
    return TestClient(app), eng


def test_pause_endpoint():
    client, eng = _make_test_client()
    resp = client.post("/api/v1/workflows/wf-123/pause")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    eng.pause.assert_called_once_with("wf-123")


def test_resume_endpoint():
    client, eng = _make_test_client()
    resp = client.post("/api/v1/workflows/wf-123/resume")
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"
    eng.resume.assert_called_once_with("wf-123")


def test_cancel_endpoint():
    client, eng = _make_test_client()
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    eng.cancel.assert_called_once_with("wf-123")


def test_pause_invalid_state_returns_409():
    eng = FakeEngine()
    eng.pause = AsyncMock(side_effect=ValueError("Cannot pause"))
    client, _ = _make_test_client(eng)
    resp = client.post("/api/v1/workflows/wf-123/pause")
    assert resp.status_code == 409


def test_cancel_not_found_returns_404():
    eng = FakeEngine()
    eng.cancel = AsyncMock(side_effect=KeyError("not found"))
    client, _ = _make_test_client(eng)
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 404
