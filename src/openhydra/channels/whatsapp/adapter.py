"""WhatsAppChannel — supports Baileys (default) and Cloud API backends."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.session import SessionStore
    from openhydra.config import WhatsAppConfig
    from openhydra.engine import Engine

logger = logging.getLogger(__name__)


class WhatsAppChannel:
    """WhatsApp channel — Baileys (QR code) or Cloud API (webhook).

    Baileys: subprocess bridge to Node.js, no business account needed.
    Cloud API: webhook on web channel, requires Meta business account + tunnel.
    """

    def __init__(
        self,
        engine: Engine,
        config: WhatsAppConfig,
        web_channel: Any = None,
        sessions: SessionStore | None = None,
        debouncer: Any = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._web_channel = web_channel
        self._sessions = sessions
        self._debouncer = debouncer
        self._handlers = None
        self._bridge = None
        self._http_client = None

    @property
    def name(self) -> str:
        return "whatsapp"

    async def start(self) -> None:
        """Start WhatsApp channel with configured backend."""
        if self._config.backend == "baileys":
            await self._start_baileys()
        else:
            await self._start_cloud_api()

        # Subscribe to engine events
        self._engine.events.on_all(self._handlers.on_engine_event)

    async def _start_baileys(self) -> None:
        """Start Baileys bridge backend."""
        from .baileys import BaileysBridge
        from .handlers import WhatsAppHandlers

        bridge_script = str(Path(__file__).parent / "bridge.js")
        auth_dir = self._config.auth_dir or ""

        self._bridge = BaileysBridge(
            bridge_script=bridge_script,
            node_path=self._config.node_path,
            auth_dir=auth_dir,
        )

        self._handlers = WhatsAppHandlers(
            engine=self._engine,
            config=self._config,
            sessions=self._sessions,
            debouncer=self._debouncer,
            bridge=self._bridge,
        )

        async def on_qr(data: str) -> None:
            logger.info("WhatsApp QR code received — scan with your phone")
            # Emit event so TUI/web can display it
            from openhydra.events import Event

            await self._engine.events.emit(Event(
                type="whatsapp.qr",
                data={"qr_data": data},
            ))

        await self._bridge.start(
            on_message=self._handlers.on_message,
            on_qr=on_qr,
        )
        logger.info("WhatsApp Baileys bridge started")

    async def _start_cloud_api(self) -> None:
        """Start Cloud API webhook backend (legacy)."""
        import httpx

        self._http_client = httpx.AsyncClient()

        from .handlers import WhatsAppHandlers

        self._handlers = WhatsAppHandlers(
            engine=self._engine,
            config=self._config,
            sessions=self._sessions,
            debouncer=self._debouncer,
            http_client=self._http_client,
        )

        # Mount routes on web channel's Starlette app
        if self._web_channel:
            app = self._web_channel.app
            if app is not None:
                for route in self._handlers.build_routes():
                    app.routes.append(route)
                logger.info("WhatsApp webhook routes mounted on web server")

    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        if self._bridge:
            await self._bridge.stop()
            self._bridge = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("WhatsApp channel stopped")

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a message to a WhatsApp user."""
        if self._handlers:
            await self._handlers.send_message(user_id, text)
