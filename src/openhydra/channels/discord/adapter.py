"""DiscordChannel — discord.py bot adapter using Gateway WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openhydra.channels.context import ChannelContext
    from openhydra.config import DiscordConfig

logger = logging.getLogger(__name__)


class DiscordChannel:
    """Discord bot channel using Gateway WebSocket (outbound — no tunnel needed)."""

    def __init__(
        self,
        config: DiscordConfig,
        ctx: ChannelContext,
    ) -> None:
        self._engine = ctx.engine
        self._config = config
        self._ctx = ctx
        self._task: asyncio.Task | None = None
        self._client = None
        self._handlers = None

    @property
    def name(self) -> str:
        return "discord"

    async def start(self) -> None:
        """Start the Discord bot (shares Engine's event loop via client.start)."""
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        from openhydra.channels.access import AccessControl

        from .handlers import DiscordHandlers

        access = AccessControl(
            allowed_ids=self._config.allowed_users,
            auth_store=self._ctx.auth_store,
            auth_manager=self._ctx.auth_manager,
        )

        self._handlers = DiscordHandlers(client, self._ctx, access)
        self._handlers.register()

        @client.event
        async def on_ready():
            await self._handlers.sync_commands()
            logger.info("Discord bot ready as %s", client.user)

        # Use client.start() (not run()) to share the event loop
        self._task = asyncio.create_task(client.start(self._config.bot_token))
        logger.info("Discord channel starting")

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Discord channel stopped")

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a Discord user via the handlers."""
        if self._handlers:
            await self._handlers.send_message(user_id, text)
