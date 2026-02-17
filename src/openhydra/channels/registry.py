"""Channel registry — manages lifecycle of all enabled channels."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import logging
from typing import TYPE_CHECKING, Any

from .base import Channel, ChannelFactory, WebMountableChannel
from .context import ChannelContext
from .permissions import ChannelPermissions
from .restricted_engine import RestrictedEngine

if TYPE_CHECKING:
    from openhydra.config import OpenHydraConfig
    from openhydra.engine import Engine

logger = logging.getLogger(__name__)

# Bundled channel modules — used as fallback when entry points aren't registered
# (e.g. editable install during development).
_BUNDLED: dict[str, str] = {
    "web": "openhydra.channels.web",
    "slack": "openhydra.channels.slack",
    "discord": "openhydra.channels.discord",
    "whatsapp": "openhydra.channels.whatsapp",
    "email": "openhydra.channels.email",
}


class ChannelRegistry:
    """Instantiate and manage all enabled messaging channels."""

    def __init__(self, engine: Engine, config: OpenHydraConfig) -> None:
        self._engine = engine
        self._config = config
        self._channels: list[Channel] = []
        self._channels_by_name: dict[str, Channel] = {}
        self._session_store = None
        self._debouncer = None
        self._approval_manager = None
        self._auth_store = None
        self._auth_manager = None

    @property
    def channels(self) -> list[Channel]:
        return list(self._channels)

    @property
    def session_store(self):
        return self._session_store

    def _init_session_store(self) -> None:
        """Create SQLite session store from the engine's database."""
        from .session import SqliteSessionStore

        self._session_store = SqliteSessionStore(self._engine.db)
        logger.info("Session store initialized")

    def _init_debouncer(self) -> None:
        """Create message debouncer from config."""
        from .debounce import DebouncerConfig, MessageDebouncer

        cfg = DebouncerConfig(
            delay_ms=self._config.channels.debounce_delay_ms,
            max_wait_ms=self._config.channels.debounce_max_wait_ms,
        )
        self._debouncer = MessageDebouncer(cfg)
        logger.info("Message debouncer initialized (delay=%dms)", cfg.delay_ms)

    def _init_auth_store(self) -> None:
        """Create SQLite auth store from the engine's database."""
        from .auth.store import AuthStore

        self._auth_store = AuthStore(self._engine.db)
        # Attach to engine for web API access
        self._engine._auth_store = self._auth_store
        logger.info("Auth store initialized")

    def _init_auth_manager(self) -> None:
        """Create and start the auth manager."""
        if not self._auth_store:
            return
        from .auth.manager import AuthManager

        self._auth_manager = AuthManager(self._auth_store, self._engine.events)
        # Attach to engine for web API access
        self._engine._auth_manager = self._auth_manager
        logger.info("Auth manager started")

    # --- Discovery -----------------------------------------------------------

    def _discover_factories(self) -> dict[str, ChannelFactory]:
        """Discover channel factories via entry points + bundled fallback."""
        factories: dict[str, ChannelFactory] = {}

        # 1. Entry points (external plugins + installed bundled)
        try:
            eps = importlib.metadata.entry_points(group="openhydra.channels")
            for ep in eps:
                try:
                    factories[ep.name] = ep.load()
                except Exception:
                    logger.warning("Channel '%s' entry point failed to load", ep.name)
        except Exception:
            logger.debug("Entry point discovery unavailable")

        # 2. Bundled fallback (dev mode — editable install may not register entry points)
        for name, module_path in _BUNDLED.items():
            if name not in factories:
                try:
                    mod = importlib.import_module(module_path)
                    fn = getattr(mod, "create_channel", None)
                    if fn is not None:
                        factories[name] = fn
                except ImportError:
                    pass

        return factories

    def _get_builtin_config(self, name: str) -> Any:
        """Map built-in channel name to its typed config object."""
        if name == "web":
            return self._config.web
        if name == "slack":
            return self._config.channels.slack
        if name == "discord":
            return self._config.channels.discord
        if name == "whatsapp":
            return self._config.channels.whatsapp
        if name == "email":
            return self._config.channels.email
        return None

    def _build_context(self, name: str) -> ChannelContext:
        """Build a ChannelContext appropriate for the channel type.

        Bundled channels get full access to the real Engine.
        External plugins get a RestrictedEngine proxy with restricted permissions.
        """
        is_bundled = name in _BUNDLED

        if is_bundled:
            permissions = ChannelPermissions.full_access()
            engine: Any = self._engine
        else:
            # Check for permission overrides in extras config
            extras_cfg = self._config.channels.extras.get(name, {})
            perm_overrides = extras_cfg.get("permissions")
            permissions = ChannelPermissions.restricted(perm_overrides)
            engine = RestrictedEngine(self._engine, permissions, name)
            logger.info(
                "Channel '%s' gets restricted engine (submit=%s, db=%s, events=%s)",
                name, permissions.can_submit, permissions.can_access_db,
                permissions.can_emit_events,
            )

        return ChannelContext(
            engine=engine,
            sessions=self._session_store,
            debouncer=self._debouncer,
            auth_store=self._auth_store,
            auth_manager=self._auth_manager,
            permissions=permissions,
        )

    def _init_channels(self) -> None:
        """Discover and instantiate enabled channels via factories."""
        factories = self._discover_factories()

        # Collect enabled channel configs
        channel_configs: dict[str, Any] = {}

        # Built-in typed configs
        for name in ("web", "slack", "discord", "whatsapp", "email"):
            cfg_obj = self._get_builtin_config(name)
            if cfg_obj and getattr(cfg_obj, "enabled", False):
                channel_configs[name] = cfg_obj

        # External extras
        for name, raw_cfg in self._config.channels.extras.items():
            if raw_cfg.get("enabled", False):
                channel_configs[name] = raw_cfg

        # Instantiate channels — web first (other channels may mount routes on it)
        order = ["web"] + [n for n in channel_configs if n != "web"]
        for name in order:
            if name not in channel_configs or name not in factories:
                continue

            # WhatsApp cloud-api requires web channel
            if name == "whatsapp":
                cfg_obj = channel_configs[name]
                backend = (
                    cfg_obj.get("backend", "baileys") if isinstance(cfg_obj, dict)
                    else getattr(cfg_obj, "backend", "baileys")
                )
                if backend == "cloud-api" and "web" not in self._channels_by_name:
                    logger.warning("WhatsApp Cloud API requires web channel to be enabled")
                    continue

            try:
                cfg = channel_configs[name]
                config_dict = cfg if isinstance(cfg, dict) else dataclasses.asdict(cfg)
                ctx = self._build_context(name)
                channel = factories[name](config_dict, ctx)
                self._channels.append(channel)
                self._channels_by_name[name] = channel
                logger.info("Channel '%s' created", name)
            except Exception:
                logger.warning("Failed to create channel '%s'", name, exc_info=True)

    async def start_all(self) -> None:
        """Initialize and start all enabled channels."""
        self._init_session_store()
        self._init_debouncer()
        self._init_auth_store()
        self._init_channels()

        for channel in self._channels:
            try:
                await channel.start()
                logger.info("Channel '%s' started", channel.name)
            except Exception:
                logger.exception("Failed to start channel '%s'", channel.name)

        # Mount web routes after all channels have started (handlers created in start())
        web_ch = self._channels_by_name.get("web")
        if web_ch:
            web_app = getattr(web_ch, "app", None)
            if web_app is not None:
                for ch in self._channels:
                    if isinstance(ch, WebMountableChannel) and ch is not web_ch:
                        try:
                            ch.mount_routes(web_app)
                        except Exception:
                            logger.warning(
                                "Failed to mount routes for channel '%s'",
                                ch.name, exc_info=True,
                            )

        # Start approval manager and auth manager after all channels
        self._init_approval_manager()
        self._init_auth_manager()

    def _init_approval_manager(self) -> None:
        """Create and start the approval manager."""
        if not self._session_store:
            return
        from .approval import ApprovalManager

        self._approval_manager = ApprovalManager(
            engine=self._engine,
            sessions=self._session_store,
            channels=self._channels_by_name,
            default_timeout=self._config.channels.approval_timeout_seconds,
            timeout_action=self._config.channels.approval_timeout_action,
        )
        self._approval_manager.start()
        logger.info("Approval manager started")

    async def stop_all(self) -> None:
        """Stop all channels in reverse order."""
        if self._approval_manager:
            self._approval_manager.stop()
            self._approval_manager = None

        if self._debouncer:
            await self._debouncer.stop()
            self._debouncer = None

        for channel in reversed(self._channels):
            try:
                await channel.stop()
                logger.info("Channel '%s' stopped", channel.name)
            except Exception:
                logger.exception("Error stopping channel '%s'", channel.name)
        self._channels.clear()
        self._channels_by_name.clear()
