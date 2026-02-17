"""WebChannel — Starlette + uvicorn web server for REST and WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from .middleware import ApiKeyMiddleware
from .routes import build_routes
from .websocket import WebSocketManager

if TYPE_CHECKING:
    from openhydra.channels.context import ChannelContext
    from openhydra.config import WebConfig

logger = logging.getLogger(__name__)


class WebChannel:
    """Web API channel — REST endpoints + WebSocket event streaming."""

    def __init__(self, config: WebConfig, ctx: ChannelContext) -> None:
        self._engine = ctx.engine
        self._config = config
        self._ws_manager = WebSocketManager(ctx.engine.events, api_key=config.api_key)
        self._server_task: asyncio.Task | None = None
        self._app: Starlette | None = None

    @property
    def name(self) -> str:
        return "web"

    @property
    def app(self) -> Starlette | None:
        """Access the Starlette app (used by WhatsApp to mount webhook routes)."""
        return self._app

    def _build_app(self) -> Starlette:
        """Build the Starlette ASGI app."""
        routes = build_routes(self._engine)
        routes.append(WebSocketRoute("/api/v1/ws", self._ws_manager.handle))

        app = Starlette(routes=routes)

        # Add API key auth middleware if configured
        if self._config.api_key:
            app.add_middleware(ApiKeyMiddleware, api_key=self._config.api_key)

        return app

    async def start(self) -> None:
        """Start the web server as a background asyncio task."""
        import uvicorn

        self._app = self._build_app()
        self._ws_manager.start()

        config = uvicorn.Config(
            app=self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        logger.info("Web server starting on %s:%d", self._config.host, self._config.port)

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a user via WebSocket broadcast."""
        await self._ws_manager.broadcast({"type": "message", "user_id": user_id, "text": text})

    async def stop(self) -> None:
        """Stop the web server."""
        self._ws_manager.stop()
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None
