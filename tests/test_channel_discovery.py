"""Tests for channel discovery and the pluggable registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from openhydra.channels.registry import _BUNDLED, ChannelRegistry
from openhydra.config import (
    ChannelsConfig,
    DiscordConfig,
    EngineConfig,
    OpenHydraConfig,
    SlackConfig,
    WebConfig,
    WhatsAppConfig,
)
from openhydra.events import EventBus


class FakeEngine:
    def __init__(self, tmp_path: Path):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-1")
        self.db = None
        self._auth_store = None
        self._auth_manager = None


def _make_config(tmp_path, web_enabled=True, slack_enabled=False, discord_enabled=False,
                 whatsapp_enabled=False):
    return OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path),
        web=WebConfig(enabled=web_enabled, port=0),
        channels=ChannelsConfig(
            slack=SlackConfig(enabled=slack_enabled, bot_token="xoxb-test", app_token="xapp-test"),
            discord=DiscordConfig(enabled=discord_enabled, bot_token="disc-test"),
            whatsapp=WhatsAppConfig(enabled=whatsapp_enabled),
        ),
    )


# --- Discovery ---


def test_discover_factories_finds_bundled(tmp_path):
    """_discover_factories returns factories for all bundled channels."""
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path)
    registry = ChannelRegistry(engine, cfg)

    factories = registry._discover_factories()
    for name in _BUNDLED:
        assert name in factories, f"Missing factory for bundled channel '{name}'"
        assert callable(factories[name])


def test_discover_factories_returns_callables(tmp_path):
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path)
    registry = ChannelRegistry(engine, cfg)

    factories = registry._discover_factories()
    for name, fn in factories.items():
        assert callable(fn), f"Factory for '{name}' is not callable"


# --- _init_channels via factories ---


def test_init_channels_creates_web_only(tmp_path):
    """With only web enabled, only web channel is created."""
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path, web_enabled=True)
    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()

    names = [ch.name for ch in registry.channels]
    assert "web" in names
    assert len(names) == 1


def test_init_channels_nothing_enabled(tmp_path):
    """No channels enabled → empty list."""
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path, web_enabled=False)
    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()

    assert registry.channels == []


# --- Extras ---


def test_extras_unknown_channel_no_factory(tmp_path):
    """Unknown extra channel with no factory is silently skipped."""
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path, web_enabled=False)
    cfg.channels.extras["telegram"] = {"enabled": True, "bot_token": "tok"}

    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()

    names = [ch.name for ch in registry.channels]
    assert "telegram" not in names


def test_extras_disabled_channel_not_created(tmp_path):
    """Disabled extra channel is not instantiated."""
    engine = FakeEngine(tmp_path)
    cfg = _make_config(tmp_path, web_enabled=False)
    cfg.channels.extras["telegram"] = {"enabled": False}

    registry = ChannelRegistry(engine, cfg)
    registry._init_channels()

    assert registry.channels == []


# --- Config parsing ---


def test_config_extras_parsed_from_raw():
    """Unknown channel keys in YAML are parsed into extras."""
    from openhydra.config import load_config

    # load_config with no file returns defaults — test that extras field exists
    cfg = load_config(config_path=Path("/nonexistent/path.yaml"))
    assert hasattr(cfg.channels, "extras")
    assert isinstance(cfg.channels.extras, dict)


# --- WebMountableChannel protocol ---


def test_whatsapp_channel_is_web_mountable():
    """WhatsApp channel implements WebMountableChannel protocol."""
    from openhydra.channels.base import WebMountableChannel
    from openhydra.channels.context import ChannelContext
    from openhydra.channels.whatsapp.adapter import WhatsAppChannel

    ctx = ChannelContext(engine=FakeEngine(Path("/tmp")))
    ch = WhatsAppChannel(WhatsAppConfig(backend="cloud-api"), ctx)
    assert isinstance(ch, WebMountableChannel)
