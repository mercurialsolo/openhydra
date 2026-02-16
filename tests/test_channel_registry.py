"""Tests for channel protocol conformance and registry lifecycle."""

from __future__ import annotations

import pytest

from openhydra.channels.base import Channel, ChannelMessage, ChannelResponse
from openhydra.channels.registry import ChannelRegistry
from openhydra.config import (
    ChannelsConfig,
    DiscordConfig,
    EngineConfig,
    MemoryConfig,
    OpenHydraConfig,
    SlackConfig,
    WebConfig,
    WhatsAppConfig,
)
from openhydra.db import Database

# --- Protocol conformance ---


class FakeChannel:
    """Minimal Channel implementation for protocol testing."""

    def __init__(self, channel_name: str = "fake") -> None:
        self._name = channel_name
        self.started = False
        self.stopped = False

    @property
    def name(self) -> str:
        return self._name

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_message(self, user_id: str, text: str) -> None:
        pass


def test_fake_channel_satisfies_protocol():
    ch = FakeChannel()
    assert isinstance(ch, Channel)


def test_channel_message_defaults():
    msg = ChannelMessage(text="hello")
    assert msg.text == "hello"
    assert msg.channel_id == ""
    assert msg.user_id == ""
    assert msg.metadata == {}


def test_channel_response_defaults():
    resp = ChannelResponse(text="ok")
    assert resp.text == "ok"
    assert resp.blocks is None


# --- Registry tests ---


def _make_config(
    tmp_path,
    *,
    web_enabled: bool = False,
    slack_enabled: bool = False,
    discord_enabled: bool = False,
    whatsapp_enabled: bool = False,
) -> OpenHydraConfig:
    return OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path),
        memory=MemoryConfig(sqlite_path=tmp_path / "memory.db"),
        web=WebConfig(enabled=web_enabled),
        channels=ChannelsConfig(
            slack=SlackConfig(enabled=slack_enabled),
            discord=DiscordConfig(enabled=discord_enabled),
            whatsapp=WhatsAppConfig(enabled=whatsapp_enabled),
        ),
    )


class FakeEngine:
    """Minimal engine stand-in for registry tests."""

    def __init__(self, tmp_path):
        from openhydra.events import EventBus

        self.events = EventBus()
        self.db = None
        self._tmp_path = tmp_path

    async def _init_db(self):
        self.db = Database(self._tmp_path / "test.db")
        await self.db.connect()


def test_registry_no_channels_enabled(tmp_path):
    """No channels instantiated when all disabled."""
    cfg = _make_config(tmp_path)
    engine = FakeEngine(tmp_path)
    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()
    assert len(registry.channels) == 0


def test_registry_channels_property_returns_copy(tmp_path):
    """channels property returns a copy, not the internal list."""
    cfg = _make_config(tmp_path)
    engine = FakeEngine(tmp_path)
    registry = ChannelRegistry(engine, cfg)
    channels = registry.channels
    channels.append("garbage")
    assert len(registry.channels) == 0


@pytest.mark.asyncio
async def test_registry_start_stop_lifecycle(tmp_path):
    """start_all and stop_all call through to channels."""
    cfg = _make_config(tmp_path)
    engine = FakeEngine(tmp_path)
    await engine._init_db()
    registry = ChannelRegistry(engine, cfg)

    # Manually inject a fake channel
    fake = FakeChannel("test")
    registry._channels.append(fake)

    await registry.start_all()
    assert fake.started

    await registry.stop_all()
    assert fake.stopped
    assert len(registry.channels) == 0

    await engine.db.close()


@pytest.mark.asyncio
async def test_registry_stop_reverses_order(tmp_path):
    """Channels stop in reverse order of start."""
    cfg = _make_config(tmp_path)
    engine = FakeEngine(tmp_path)
    await engine._init_db()
    registry = ChannelRegistry(engine, cfg)

    stop_order = []

    class OrderedFake:
        def __init__(self, n):
            self._name = n

        @property
        def name(self):
            return self._name

        async def start(self):
            pass

        async def stop(self):
            stop_order.append(self._name)

        async def send_message(self, user_id, text):
            pass

    registry._channels = [OrderedFake("a"), OrderedFake("b"), OrderedFake("c")]
    await registry.stop_all()
    assert stop_order == ["c", "b", "a"]

    await engine.db.close()


@pytest.mark.asyncio
async def test_registry_start_handles_channel_failure(tmp_path):
    """A channel failing to start doesn't prevent others from starting."""
    cfg = _make_config(tmp_path)
    engine = FakeEngine(tmp_path)
    await engine._init_db()
    registry = ChannelRegistry(engine, cfg)

    class FailChannel:
        @property
        def name(self):
            return "fail"

        async def start(self):
            raise RuntimeError("boom")

        async def stop(self):
            pass

        async def send_message(self, user_id, text):
            pass

    good = FakeChannel("good")
    registry._channels = [FailChannel(), good]

    # Should not raise — logs the error and continues
    await registry.start_all()
    assert good.started

    await engine.db.close()


def test_whatsapp_cloud_api_requires_web_channel(tmp_path):
    """WhatsApp Cloud API channel is skipped when web is disabled."""
    cfg = _make_config(tmp_path, whatsapp_enabled=True, web_enabled=False)
    cfg.channels.whatsapp.backend = "cloud-api"
    engine = FakeEngine(tmp_path)
    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()
    # WhatsApp should not be present (web required for cloud-api)
    names = [ch.name for ch in registry.channels]
    assert "whatsapp" not in names
