"""SlackChannel — slack-bolt async adapter with Socket Mode."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.session import SessionStore
    from openhydra.config import SlackConfig
    from openhydra.engine import Engine

logger = logging.getLogger(__name__)


class SlackChannel:
    """Slack bot channel using Socket Mode (outbound connection — no tunnel needed)."""

    def __init__(
        self,
        engine: Engine,
        config: SlackConfig,
        sessions: SessionStore | None = None,
        debouncer: Any = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._sessions = sessions
        self._debouncer = debouncer
        self._task: asyncio.Task | None = None
        self._handlers = None

    @property
    def name(self) -> str:
        return "slack"

    async def start(self) -> None:
        """Start the Slack bot with Socket Mode."""
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        bolt_app = AsyncApp(token=self._config.bot_token)

        from .handlers import SlackHandlers

        self._handlers = SlackHandlers(
            bolt_app,
            self._engine,
            sessions=self._sessions,
            allowed_users=self._config.allowed_users,
            debouncer=self._debouncer,
        )
        self._handlers.register()

        # Subscribe to engine events
        self._engine.events.on_all(self._handlers.on_engine_event)

        handler = AsyncSocketModeHandler(bolt_app, self._config.app_token)
        self._task = asyncio.create_task(handler.start_async())
        logger.info("Slack channel started (Socket Mode)")

    async def stop(self) -> None:
        """Stop the Slack bot."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Slack channel stopped")

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a Slack user via the handlers."""
        if self._handlers:
            await self._handlers.send_message(user_id, text)
