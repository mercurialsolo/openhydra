"""HeartbeatRunner — periodic autonomous agent execution."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.session import SessionStore
    from openhydra.config import HeartbeatConfig
    from openhydra.db import Database
    from openhydra.engine import Engine
    from openhydra.events import Event

logger = logging.getLogger(__name__)


class HeartbeatRunner:
    """Periodic autonomous agent execution.

    Runs on a timer, polls pending system events from DB, builds a prompt,
    submits to engine, and delivers results via the user's active channel.
    """

    def __init__(
        self,
        engine: Engine,
        db: Database,
        config: HeartbeatConfig,
        sessions: SessionStore | None = None,
        channels: dict[str, Channel] | None = None,
    ) -> None:
        self._engine = engine
        self._db = db
        self._config = config
        self._sessions = sessions
        self._channels = channels or {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the heartbeat loop as background task."""
        if not self._config.enabled:
            logger.debug("Heartbeat disabled, not starting")
            return
        self._subscribe_workflow_events()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Heartbeat started (interval=%.0fs)", self._config.interval_seconds
        )

    async def stop(self) -> None:
        """Cancel the heartbeat loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heartbeat stopped")

    async def enqueue_event(self, event_type: str, data: dict | None = None) -> None:
        """Add system event for next heartbeat to process."""
        event_id = str(uuid.uuid4())
        data_json = json.dumps(data or {})
        await self._db.conn.execute(
            "INSERT INTO heartbeat_events (id, type, data) VALUES (?, ?, ?)",
            (event_id, event_type, data_json),
        )
        await self._db.conn.commit()

    async def _loop(self) -> None:
        """Main heartbeat loop."""
        try:
            while True:
                await asyncio.sleep(self._config.interval_seconds)
                if self._is_quiet_hours():
                    logger.debug("Quiet hours, skipping heartbeat tick")
                    continue
                try:
                    await self._tick()
                except Exception:
                    logger.exception("Heartbeat tick failed")
        except asyncio.CancelledError:
            return

    async def _tick(self) -> None:
        """Single heartbeat tick."""
        # Poll pending events
        cursor = await self._db.conn.execute(
            "SELECT id, type, data FROM heartbeat_events "
            "WHERE processed = 0 ORDER BY created_at LIMIT 20"
        )
        rows = await cursor.fetchall()

        if not rows:
            return

        # Build prompt from events
        event_summaries = []
        event_ids = []
        for row in rows:
            event_ids.append(row["id"])
            data = {}
            try:
                data = json.loads(row["data"]) if row["data"] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            event_summaries.append(f"- [{row['type']}] {json.dumps(data)}")

        prompt = (
            "You are an autonomous assistant checking in. "
            "The following system events occurred since last check:\n"
            + "\n".join(event_summaries)
            + "\n\nProvide a brief status update or take any needed actions."
        )

        # Submit to engine
        try:
            workflow_id = await self._engine.submit(prompt)
            logger.info("Heartbeat submitted workflow %s for %d events", workflow_id[:8], len(rows))
        except Exception:
            logger.exception("Heartbeat failed to submit workflow")
            return

        # Mark events as processed
        now = datetime.now(timezone.utc).isoformat()
        for eid in event_ids:
            await self._db.conn.execute(
                "UPDATE heartbeat_events SET processed = 1, processed_at = ? WHERE id = ?",
                (now, eid),
            )
        await self._db.conn.commit()

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        start = self._config.quiet_hours_start
        end = self._config.quiet_hours_end
        if start is None or end is None:
            return False
        now_hour = datetime.now().hour
        if start <= end:
            return start <= now_hour < end
        else:
            # Wraps midnight (e.g. 22-06)
            return now_hour >= start or now_hour < end

    def _subscribe_workflow_events(self) -> None:
        """Auto-enqueue workflow completion/failure events."""
        self._engine.events.on("workflow.completed", self._on_workflow_event)
        self._engine.events.on("workflow.failed", self._on_workflow_event)

    async def _on_workflow_event(self, event: Event) -> None:
        """Enqueue workflow events for next heartbeat."""
        await self.enqueue_event(event.type, event.data)
