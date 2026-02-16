"""Tests for WebSocket authentication and API key auto-generation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from openhydra.channels.web.websocket import WebSocketManager
from openhydra.config import OpenHydraConfig, ensure_api_key
from openhydra.events import EventBus

# ---------------------------------------------------------------------------
# WebSocket auth
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Minimal WebSocket mock with query_params support."""

    def __init__(self, query_params: dict | None = None):
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""
        self.sent: list[str] = []
        self._incoming: list[str] = []
        self._receive_index = 0
        self.query_params = query_params or {}

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_text(self, data: str):
        self.sent.append(data)

    async def receive_text(self) -> str:
        if self._receive_index < len(self._incoming):
            msg = self._incoming[self._receive_index]
            self._receive_index += 1
            return msg
        from starlette.websockets import WebSocketDisconnect
        raise WebSocketDisconnect(code=1000)


@pytest.mark.asyncio
async def test_ws_no_auth_when_no_key():
    """When no API key is set, WebSocket accepts without checking."""
    bus = EventBus()
    manager = WebSocketManager(bus, api_key="")
    ws = FakeWebSocket()
    await manager.handle(ws)
    assert ws.accepted is True


@pytest.mark.asyncio
async def test_ws_rejects_missing_key():
    """When API key is set, reject connections without it."""
    bus = EventBus()
    manager = WebSocketManager(bus, api_key="secret123")
    ws = FakeWebSocket(query_params={})
    await manager.handle(ws)
    assert ws.closed is True
    assert ws.close_code == 4001
    assert ws.accepted is False


@pytest.mark.asyncio
async def test_ws_rejects_wrong_key():
    """When API key is set, reject connections with wrong key."""
    bus = EventBus()
    manager = WebSocketManager(bus, api_key="secret123")
    ws = FakeWebSocket(query_params={"api_key": "wrong"})
    await manager.handle(ws)
    assert ws.closed is True
    assert ws.close_code == 4001


@pytest.mark.asyncio
async def test_ws_accepts_correct_key():
    """When API key is set, accept connections with correct key."""
    bus = EventBus()
    manager = WebSocketManager(bus, api_key="secret123")
    ws = FakeWebSocket(query_params={"api_key": "secret123"})
    await manager.handle(ws)
    assert ws.accepted is True
    assert ws.closed is False


# ---------------------------------------------------------------------------
# ensure_api_key
# ---------------------------------------------------------------------------


def test_ensure_api_key_generates_when_empty(tmp_path, monkeypatch):
    """Generates and persists API key when empty."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = OpenHydraConfig()
    assert config.web.api_key == ""

    ensure_api_key(config)

    assert len(config.web.api_key) == 32  # hex(16) = 32 chars
    # Check it was persisted
    user_config = tmp_path / ".openhydra" / "openhydra.yaml"
    assert user_config.exists()
    data = yaml.safe_load(user_config.read_text())
    assert data["web"]["api_key"] == config.web.api_key


def test_ensure_api_key_noop_when_set(tmp_path, monkeypatch):
    """Does nothing when API key is already set."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = OpenHydraConfig()
    config.web.api_key = "existing-key"

    ensure_api_key(config)

    assert config.web.api_key == "existing-key"
    # No file written
    user_config = tmp_path / ".openhydra" / "openhydra.yaml"
    assert not user_config.exists()


def test_ensure_api_key_preserves_existing_config(tmp_path, monkeypatch):
    """Preserves existing config when writing new API key."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_dir = tmp_path / ".openhydra"
    config_dir.mkdir()
    config_file = config_dir / "openhydra.yaml"
    config_file.write_text(
        yaml.safe_dump({"agents": {"default_provider": "anthropic-api"}})
    )

    config = OpenHydraConfig()
    ensure_api_key(config)

    data = yaml.safe_load(config_file.read_text())
    assert data["agents"]["default_provider"] == "anthropic-api"
    assert data["web"]["api_key"] == config.web.api_key


# ---------------------------------------------------------------------------
# WebChannel passes api_key to WebSocketManager
# ---------------------------------------------------------------------------


def test_web_channel_passes_api_key():
    """WebChannel passes api_key from config to WebSocketManager."""
    from openhydra.channels.web.server import WebChannel
    from openhydra.config import WebConfig

    class FakeEngine:
        def __init__(self):
            self.events = EventBus()

    engine = FakeEngine()
    ch = WebChannel(engine, WebConfig(api_key="test-key"))
    assert ch._ws_manager._api_key == "test-key"
