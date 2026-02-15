"""SQLite database schema and connection management."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'created',
    input TEXT NOT NULL,
    plan TEXT,
    current_step INTEGER DEFAULT 0,
    config TEXT,
    error TEXT,
    total_cost_usd REAL DEFAULT 0.0,
    total_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    ordinal INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    instructions TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_data TEXT,
    output_data TEXT,
    artifacts TEXT,
    cost_usd REAL DEFAULT 0.0,
    tokens_used INTEGER DEFAULT 0,
    error TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    step_id TEXT REFERENCES steps(id),
    type TEXT NOT NULL DEFAULT 'approval',
    prompt TEXT NOT NULL,
    response TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_steps_workflow ON steps(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approvals_workflow ON approvals(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status) WHERE status = 'pending';
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open database connection and ensure schema exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
