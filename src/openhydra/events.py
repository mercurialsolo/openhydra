"""Async event bus for decoupling core engine from interfaces."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine


@dataclass
class Event:
    """An event emitted by the core engine."""

    type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Known event types (not enforced, just documented)
WORKFLOW_CREATED = "workflow.created"
WORKFLOW_PLANNING = "workflow.planning"
WORKFLOW_EXECUTING = "workflow.executing"
WORKFLOW_COMPLETED = "workflow.completed"
WORKFLOW_FAILED = "workflow.failed"
WORKFLOW_WAITING = "workflow.waiting"
STEP_STARTED = "step.started"
STEP_PROGRESS = "step.progress"
STEP_COMPLETED = "step.completed"
STEP_FAILED = "step.failed"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_RESOLVED = "approval.resolved"
MEMORY_STORED = "memory.stored"
COST_UPDATED = "cost.updated"
ARTIFACT_CREATED = "artifact.created"
ARTIFACT_MODIFIED = "artifact.modified"
MESSAGE_SENT = "message.sent"

EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async publish/subscribe event bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to events of a specific type."""
        self._handlers[event_type].append(handler)

    def on_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._wildcard_handlers.append(handler)

    def off(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe from events of a specific type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribed handlers."""
        handlers = self._handlers.get(event.type, []) + self._wildcard_handlers
        if handlers:
            await asyncio.gather(
                *(h(event) for h in handlers),
                return_exceptions=True,
            )
