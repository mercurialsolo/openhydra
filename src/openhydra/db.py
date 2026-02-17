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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paused_at TIMESTAMP,
    paused_by TEXT DEFAULT ''
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
    depends_on TEXT DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    from_step TEXT NOT NULL,
    to_step TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_steps_workflow ON steps(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approvals_workflow ON approvals(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_messages_workflow ON messages(workflow_id);
CREATE INDEX IF NOT EXISTS idx_messages_to_step ON messages(to_step);

CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    active_workflow_id TEXT,
    last_channel TEXT NOT NULL DEFAULT '',
    last_message_at TIMESTAMP,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_workflow
    ON sessions(active_workflow_id) WHERE active_workflow_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS heartbeat_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    data TEXT DEFAULT '{}',
    processed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_pending
    ON heartbeat_events(processed) WHERE processed = 0;

-- Skill security scanning
CREATE TABLE IF NOT EXISTS skill_approvals (
    skill_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending_review',
    source_path TEXT DEFAULT '',
    scan_result_json TEXT DEFAULT '',
    approved_by TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skill_approvals_status ON skill_approvals(status);

-- Channel authorization
CREATE TABLE IF NOT EXISTS authorized_identities (
    identity_key TEXT PRIMARY KEY,  -- "channel:user_id"
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT DEFAULT '',
    authorized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    authorized_via TEXT DEFAULT 'auth_code'
);
CREATE INDEX IF NOT EXISTS idx_auth_identities_channel ON authorized_identities(channel);

CREATE TABLE IF NOT EXISTS auth_challenges (
    code TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    resolved INTEGER DEFAULT 0
);

-- Agenda items for scheduled autonomous tasks
CREATE TABLE IF NOT EXISTS agenda_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'assistant_md',
    schedule TEXT NOT NULL,
    instruction TEXT NOT NULL,
    permission TEXT NOT NULL DEFAULT 'read',
    enabled INTEGER DEFAULT 1,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    run_count INTEGER DEFAULT 0,
    last_workflow_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agenda_enabled ON agenda_items(enabled) WHERE enabled = 1;
CREATE INDEX IF NOT EXISTS idx_agenda_next_run ON agenda_items(next_run_at) WHERE enabled = 1;

-- Delivery queue for autonomous task results
CREATE TABLE IF NOT EXISTS delivery_queue (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    recipient_channel TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    subject TEXT DEFAULT '',
    body TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_delivery_pending
    ON delivery_queue(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_delivery_recipient
    ON delivery_queue(recipient_channel, recipient_id);
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
        await self._migrate()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _migrate(self) -> None:
        """Apply idempotent schema migrations for columns added after initial release."""
        for sql in [
            "ALTER TABLE workflows ADD COLUMN paused_at TIMESTAMP",
            "ALTER TABLE workflows ADD COLUMN paused_by TEXT DEFAULT ''",
        ]:
            try:
                await self._conn.execute(sql)
            except Exception:
                pass  # Column already exists
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
