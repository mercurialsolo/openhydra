"""WhatsApp message handlers — supports both Baileys and Cloud API backends."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .formatters import event_to_text

if TYPE_CHECKING:
    import httpx

    from openhydra.channels.session import SessionStore
    from openhydra.channels.whatsapp.baileys import BaileysBridge
    from openhydra.config import WhatsAppConfig
    from openhydra.engine import Engine
    from openhydra.events import Event

logger = logging.getLogger(__name__)

META_API_URL = "https://graph.facebook.com/v18.0"


class WhatsAppHandlers:
    """Routes WhatsApp messages to Engine — works with both Baileys and Cloud API."""

    def __init__(
        self,
        engine: Engine,
        config: WhatsAppConfig,
        sessions: SessionStore | None = None,
        debouncer: Any = None,
        bridge: BaileysBridge | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._sessions = sessions
        self._debouncer = debouncer
        self._bridge = bridge
        self._http = http_client
        # Fallback in-memory map when no session store
        self._conversations: dict[str, str] = {}

    def _is_allowed(self, phone: str) -> bool:
        if not self._config.allowed_phones:
            return True
        return phone in self._config.allowed_phones

    def build_routes(self) -> list:
        """Build Starlette routes for Cloud API webhooks."""
        from starlette.requests import Request
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.routing import Route

        async def verify(request: Request) -> PlainTextResponse:
            mode = request.query_params.get("hub.mode", "")
            token = request.query_params.get("hub.verify_token", "")
            challenge = request.query_params.get("hub.challenge", "")
            if mode == "subscribe" and token == self._config.verify_token:
                return PlainTextResponse(challenge)
            return PlainTextResponse("Forbidden", status_code=403)

        async def webhook(request: Request) -> JSONResponse:
            body = await request.json()
            messages = self._extract_messages(body)
            for phone, text in messages:
                await self.on_message(phone, text)
            return JSONResponse({"status": "ok"})

        return [
            Route("/webhooks/whatsapp", verify, methods=["GET"]),
            Route("/webhooks/whatsapp", webhook, methods=["POST"]),
        ]

    def _extract_messages(self, body: dict[str, Any]) -> list[tuple[str, str]]:
        """Extract (phone_number, text) pairs from webhook payload."""
        results = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") == "text":
                        phone = msg.get("from", "")
                        text = msg.get("text", {}).get("body", "")
                        if phone and text:
                            results.append((phone, text))
        return results

    async def on_message(self, phone: str, text: str) -> None:
        """Process an inbound message — submit task or handle approval."""
        if not self._is_allowed(phone):
            return

        text_lower = text.strip().lower()

        # Check for approval commands
        if text_lower == "approve":
            wf_id = self._conversations.get(phone)
            if not wf_id and self._sessions:
                session = await self._sessions.get(f"whatsapp:{phone}")
                if session:
                    wf_id = session.active_workflow_id
            if wf_id:
                await self._engine.approve(wf_id)
                await self.send_message(phone, "Approved.")
            else:
                await self.send_message(phone, "No active workflow to approve.")
            return

        if text_lower.startswith("reject"):
            wf_id = self._conversations.get(phone)
            if not wf_id and self._sessions:
                session = await self._sessions.get(f"whatsapp:{phone}")
                if session:
                    wf_id = session.active_workflow_id
            if wf_id:
                reason = text[6:].strip() or "Rejected via WhatsApp"
                await self._engine.reject(wf_id, reason)
                await self.send_message(phone, "Rejected.")
            else:
                await self.send_message(phone, "No active workflow to reject.")
            return

        # Debounce if configured
        if self._debouncer:
            combined = await self._debouncer.debounce(f"whatsapp:{phone}", text)
            if combined is None:
                return
            text = combined

        # Submit as new task
        workflow_id = await self._engine.submit(text)
        self._conversations[phone] = workflow_id

        # Store in session if available
        if self._sessions:
            from openhydra.channels.session import ChannelSession

            session = ChannelSession(
                session_key=f"whatsapp:{phone}",
                active_workflow_id=workflow_id,
                last_channel="whatsapp",
                last_message_at=datetime.now(timezone.utc),
                metadata={"phone": phone},
            )
            await self._sessions.upsert(session)

        await self.send_message(phone, f"Workflow {workflow_id[:8]} started: {text}")

    async def send_message(self, to: str, text: str) -> None:
        """Send a text message via Baileys bridge or Meta Cloud API."""
        if self._bridge:
            try:
                await self._bridge.send(to, text)
            except Exception:
                logger.exception("Failed to send WhatsApp message via Baileys to %s", to)
        elif self._http:
            await self._send_cloud_api(to, text)

    async def _send_cloud_api(self, to: str, text: str) -> None:
        """Send via Meta Cloud API."""
        url = f"{META_API_URL}/{self._config.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        headers = {"Authorization": f"Bearer {self._config.access_token}"}
        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("WhatsApp API error: %d %s", resp.status_code, resp.text)
        except Exception:
            logger.exception("Failed to send WhatsApp message to %s", to)

    async def on_engine_event(self, event: Event) -> None:
        """Forward engine events to the relevant WhatsApp conversation."""
        wf_id = event.data.get("workflow_id", "")

        # Find phone for this workflow
        phone = None
        for p, w in self._conversations.items():
            if w == wf_id:
                phone = p
                break

        if not phone and self._sessions:
            session = await self._sessions.find_by_workflow(wf_id)
            if session and session.last_channel == "whatsapp":
                phone = session.metadata.get("phone", "")

        if not phone:
            return

        text = event_to_text(event)
        await self.send_message(phone, text)

        # Cleanup when workflow finishes
        if event.type in ("workflow.completed", "workflow.failed"):
            self._conversations.pop(phone, None)
            if self._sessions:
                await self._sessions.clear_workflow(wf_id)
