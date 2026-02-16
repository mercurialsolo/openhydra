"""WebSocket manager — broadcasts engine events to connected clients."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from openhydra.events import Event, EventBus

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts engine events."""

    def __init__(self, events: EventBus) -> None:
        self._events = events
        self._connections: list[WebSocket] = []
        self._subscriptions: dict[int, str | None] = {}  # id(ws) → workflow_id or None (all)
        self._handler = self._on_event  # store bound ref for identity comparison

    def start(self) -> None:
        """Subscribe to engine events."""
        self._events.on_all(self._handler)

    def stop(self) -> None:
        """Unsubscribe from engine events."""
        self._events._wildcard_handlers = [
            h for h in self._events._wildcard_handlers if h is not self._handler
        ]

    async def handle(self, websocket: WebSocket) -> None:
        """Handle a single WebSocket connection lifecycle."""
        await websocket.accept()
        self._connections.append(websocket)
        ws_id = id(websocket)
        self._subscriptions[ws_id] = None  # Not subscribed to any workflow yet

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if "subscribe" in msg:
                        sub = msg["subscribe"]
                        self._subscriptions[ws_id] = sub if sub != "*" else None
                except (json.JSONDecodeError, KeyError):
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            self._connections.remove(websocket)
            self._subscriptions.pop(ws_id, None)

    async def _on_event(self, event: Event) -> None:
        """Broadcast an event to all connected (and subscribed) clients."""
        payload = self._serialize_event(event)
        dead: list[WebSocket] = []

        for ws in self._connections:
            ws_id = id(ws)
            sub_filter = self._subscriptions.get(ws_id)

            # Filter by workflow_id if client subscribed to a specific one
            if sub_filter is not None:
                event_wf = event.data.get("workflow_id", "")
                if event_wf != sub_filter:
                    continue

            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections.remove(ws)
            self._subscriptions.pop(id(ws), None)

    def _serialize_event(self, event: Event) -> str:
        return json.dumps(self._event_to_dict(event))

    def _event_to_dict(self, event: Event) -> dict[str, Any]:
        return {
            "event": event.type,
            "data": event.data,
            "ts": event.timestamp.isoformat(),
        }

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON payload to all connected clients."""
        payload = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)
            self._subscriptions.pop(id(ws), None)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
