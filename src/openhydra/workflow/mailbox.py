"""Mailbox — DB-backed message passing between workflow steps."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..db import Database
from ..events import MESSAGE_SENT, Event, EventBus


@dataclass
class Message:
    """A message between workflow steps."""

    id: str = ""
    workflow_id: str = ""
    from_step: str = ""
    to_step: str | None = None  # None = broadcast
    subject: str = ""
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: datetime | None = None


class Mailbox:
    """DB-backed message passing between workflow steps.

    Messages are persisted in SQLite and injected into receiving
    agent's instructions by the RoleExecutor.
    """

    def __init__(self, db: Database, events: EventBus) -> None:
        self._db = db
        self._events = events

    async def send(
        self,
        workflow_id: str,
        from_step: str,
        to_step: str | None,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Send a message. to_step=None for broadcast."""
        msg_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        await self._db.conn.execute(
            "INSERT INTO messages "
            "(id, workflow_id, from_step, to_step, subject, body, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, workflow_id, from_step, to_step, subject, body,
             json.dumps(metadata or {}), now),
        )
        await self._db.conn.commit()

        await self._events.emit(Event(
            type=MESSAGE_SENT,
            data={
                "workflow_id": workflow_id,
                "message_id": msg_id,
                "from_step": from_step,
                "to_step": to_step,
                "subject": subject,
            },
        ))
        return msg_id

    async def receive(self, workflow_id: str, step_id: str) -> list[Message]:
        """Get all messages addressed to a step or broadcast."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM messages WHERE workflow_id = ? AND (to_step = ? OR to_step IS NULL) "
            "ORDER BY created_at",
            (workflow_id, step_id),
        )
        rows = await cursor.fetchall()

        messages = []
        for row in rows:
            messages.append(Message(
                id=row["id"],
                workflow_id=row["workflow_id"],
                from_step=row["from_step"],
                to_step=row["to_step"],
                subject=row["subject"],
                body=row["body"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=datetime.fromisoformat(row["created_at"]),
                read_at=datetime.fromisoformat(row["read_at"]) if row["read_at"] else None,
            ))

        # Mark as read
        now = datetime.now(timezone.utc).isoformat()
        for msg in messages:
            if msg.read_at is None:
                await self._db.conn.execute(
                    "UPDATE messages SET read_at = ? WHERE id = ?",
                    (now, msg.id),
                )
        await self._db.conn.commit()

        return messages

    async def list_messages(self, workflow_id: str) -> list[Message]:
        """List all messages in a workflow."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM messages WHERE workflow_id = ? ORDER BY created_at",
            (workflow_id,),
        )
        rows = await cursor.fetchall()
        return [
            Message(
                id=row["id"],
                workflow_id=row["workflow_id"],
                from_step=row["from_step"],
                to_step=row["to_step"],
                subject=row["subject"],
                body=row["body"],
            )
            for row in rows
        ]
