"""Session persistence — tracks which user is on which channel with which workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from openhydra.db import Database


@dataclass
class ChannelSession:
    """A user's channel session."""

    session_key: str  # "{channel}:{user_id}"
    active_workflow_id: str | None = None
    last_channel: str = ""
    last_message_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session persistence."""

    async def get(self, session_key: str) -> ChannelSession | None: ...
    async def upsert(self, session: ChannelSession) -> None: ...
    async def find_by_workflow(self, workflow_id: str) -> ChannelSession | None: ...
    async def clear_workflow(self, workflow_id: str) -> None: ...


class SqliteSessionStore:
    """SQLite-backed session store."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, session_key: str) -> ChannelSession | None:
        cursor = await self._db.conn.execute(
            "SELECT session_key, active_workflow_id, last_channel, last_message_at, metadata "
            "FROM sessions WHERE session_key = ?",
            (session_key,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    async def upsert(self, session: ChannelSession) -> None:
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(session.metadata)
        last_msg = session.last_message_at.isoformat() if session.last_message_at else None
        await self._db.conn.execute(
            "INSERT INTO sessions (session_key, active_workflow_id, last_channel, "
            "last_message_at, metadata, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_key) DO UPDATE SET "
            "active_workflow_id = excluded.active_workflow_id, "
            "last_channel = excluded.last_channel, "
            "last_message_at = excluded.last_message_at, "
            "metadata = excluded.metadata, "
            "updated_at = excluded.updated_at",
            (session.session_key, session.active_workflow_id, session.last_channel,
             last_msg, metadata_json, now),
        )
        await self._db.conn.commit()

    async def find_by_workflow(self, workflow_id: str) -> ChannelSession | None:
        cursor = await self._db.conn.execute(
            "SELECT session_key, active_workflow_id, last_channel, last_message_at, metadata "
            "FROM sessions WHERE active_workflow_id = ?",
            (workflow_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    async def clear_workflow(self, workflow_id: str) -> None:
        await self._db.conn.execute(
            "UPDATE sessions SET active_workflow_id = NULL, updated_at = ? "
            "WHERE active_workflow_id = ?",
            (datetime.now(timezone.utc).isoformat(), workflow_id),
        )
        await self._db.conn.commit()

    def _row_to_session(self, row) -> ChannelSession:
        last_msg = None
        if row["last_message_at"]:
            try:
                last_msg = datetime.fromisoformat(row["last_message_at"])
            except (ValueError, TypeError):
                pass
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        return ChannelSession(
            session_key=row["session_key"],
            active_workflow_id=row["active_workflow_id"],
            last_channel=row["last_channel"],
            last_message_at=last_msg,
            metadata=metadata,
        )
