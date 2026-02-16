"""Channel registry — manages lifecycle of all enabled channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import Channel

if TYPE_CHECKING:
    from openhydra.config import OpenHydraConfig
    from openhydra.engine import Engine

logger = logging.getLogger(__name__)


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

    def _init_channels(self) -> None:
        """Discover and instantiate enabled channels. Lazy imports so missing deps don't crash."""
        # Web channel — always first (Cloud API WhatsApp mounts on it)
        if self._config.web.enabled:
            try:
                from .web.server import WebChannel

                channel = WebChannel(self._engine, self._config.web)
                self._channels.append(channel)
                self._channels_by_name["web"] = channel
                logger.info(
                    "Web channel enabled on %s:%d", self._config.web.host, self._config.web.port,
                )
            except ImportError:
                logger.warning(
                    "Web channel deps not installed (pip install openhydra[web])",
                )

        # Slack channel
        if self._config.channels.slack.enabled:
            try:
                from .slack.adapter import SlackChannel

                channel = SlackChannel(
                    self._engine,
                    self._config.channels.slack,
                    sessions=self._session_store,
                    debouncer=self._debouncer,
                )
                self._channels.append(channel)
                self._channels_by_name["slack"] = channel
                logger.info("Slack channel enabled")
            except ImportError:
                logger.warning("Slack dependencies not installed (pip install openhydra[slack])")

        # Discord channel
        if self._config.channels.discord.enabled:
            try:
                from .discord.adapter import DiscordChannel

                channel = DiscordChannel(
                    self._engine,
                    self._config.channels.discord,
                    sessions=self._session_store,
                    debouncer=self._debouncer,
                )
                self._channels.append(channel)
                self._channels_by_name["discord"] = channel
                logger.info("Discord channel enabled")
            except ImportError:
                logger.warning(
                    "Discord deps not installed (pip install openhydra[discord])",
                )

        # WhatsApp channel
        if self._config.channels.whatsapp.enabled:
            backend = self._config.channels.whatsapp.backend
            if backend == "cloud-api":
                web_channel = self._get_web_channel()
                if web_channel is None:
                    logger.warning("WhatsApp Cloud API requires web channel to be enabled")
                    return
            else:
                web_channel = None

            try:
                from .whatsapp.adapter import WhatsAppChannel

                channel = WhatsAppChannel(
                    self._engine,
                    self._config.channels.whatsapp,
                    web_channel=web_channel,
                    sessions=self._session_store,
                    debouncer=self._debouncer,
                )
                self._channels.append(channel)
                self._channels_by_name["whatsapp"] = channel
                logger.info("WhatsApp channel enabled (backend=%s)", backend)
            except ImportError:
                logger.warning(
                    "WhatsApp dependencies not installed (pip install openhydra[whatsapp])"
                )

    def _get_web_channel(self) -> Channel | None:
        """Find the web channel if it's been registered."""
        return self._channels_by_name.get("web")

    async def start_all(self) -> None:
        """Initialize and start all enabled channels."""
        self._init_session_store()
        self._init_debouncer()
        self._init_channels()

        for channel in self._channels:
            try:
                await channel.start()
                logger.info("Channel '%s' started", channel.name)
            except Exception:
                logger.exception("Failed to start channel '%s'", channel.name)

        # Start approval manager after all channels
        self._init_approval_manager()

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
