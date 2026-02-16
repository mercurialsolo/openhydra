"""Tests for WebSocket event broadcasting."""

from __future__ import annotations

import json

import pytest

from openhydra.channels.web.websocket import WebSocketManager
from openhydra.events import Event, EventBus


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self):
        self.accepted = False
        self.sent: list[str] = []
        self._incoming: list[str] = []
        self._receive_index = 0

    async def accept(self):
        self.accepted = True

    async def send_text(self, data: str):
        self.sent.append(data)

    def queue_message(self, msg: str):
        self._incoming.append(msg)

    async def receive_text(self) -> str:
        if self._receive_index < len(self._incoming):
            msg = self._incoming[self._receive_index]
            self._receive_index += 1
            return msg
        # Simulate disconnect
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect(code=1000)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def manager(bus):
    return WebSocketManager(bus)


@pytest.mark.asyncio
async def test_event_broadcast(bus, manager):
    """Events are serialized and sent to connected clients."""
    manager.start()
    ws = FakeWebSocket()

    # Simulate connection + immediate disconnect
    await manager.handle(ws)

    # After disconnect, ws should be removed
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_subscription_filtering(bus, manager):
    """Clients subscribed to a specific workflow only receive matching events."""
    manager.start()

    # Manually add a fake WebSocket to connections
    ws = FakeWebSocket()
    ws.accepted = True
    manager._connections.append(ws)
    manager._subscriptions[id(ws)] = "wf-abc"

    # Broadcast a matching event
    event = Event(type="step.completed", data={"workflow_id": "wf-abc", "step": 1})
    await manager._on_event(event)
    assert len(ws.sent) == 1

    # Broadcast a non-matching event
    event2 = Event(type="step.completed", data={"workflow_id": "wf-other"})
    await manager._on_event(event2)
    assert len(ws.sent) == 1  # Still 1, not 2


@pytest.mark.asyncio
async def test_wildcard_subscription(bus, manager):
    """Clients with no filter receive all events."""
    manager.start()

    ws = FakeWebSocket()
    ws.accepted = True
    manager._connections.append(ws)
    manager._subscriptions[id(ws)] = None  # wildcard

    event = Event(type="step.completed", data={"workflow_id": "wf-any"})
    await manager._on_event(event)
    assert len(ws.sent) == 1


@pytest.mark.asyncio
async def test_event_serialization(bus, manager):
    """Events are serialized to JSON with event, data, ts fields."""
    manager.start()

    ws = FakeWebSocket()
    ws.accepted = True
    manager._connections.append(ws)
    manager._subscriptions[id(ws)] = None

    event = Event(type="workflow.created", data={"workflow_id": "wf-1"})
    await manager._on_event(event)

    payload = json.loads(ws.sent[0])
    assert payload["event"] == "workflow.created"
    assert payload["data"]["workflow_id"] == "wf-1"
    assert "ts" in payload


@pytest.mark.asyncio
async def test_dead_connection_removed(bus, manager):
    """Dead connections are cleaned up on broadcast."""
    manager.start()

    class DeadSocket:
        async def send_text(self, _data):
            raise ConnectionError("gone")

    ws = DeadSocket()
    manager._connections.append(ws)
    manager._subscriptions[id(ws)] = None

    event = Event(type="test", data={})
    await manager._on_event(event)

    assert manager.connection_count == 0


def test_stop_unsubscribes(bus, manager):
    """stop() removes the event handler."""
    manager.start()
    assert len(bus._wildcard_handlers) == 1
    manager.stop()
    assert len(bus._wildcard_handlers) == 0
