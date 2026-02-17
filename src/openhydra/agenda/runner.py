"""AgendaRunner — superset of HeartbeatRunner with scheduled task execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..assistant import parse_interests, parse_schedule
from .delivery import DeliveryService
from .schedule import is_due, next_run

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.session import SessionStore
    from openhydra.config import HeartbeatConfig
    from openhydra.db import Database
    from openhydra.engine import Engine
    from openhydra.events import Event

logger = logging.getLogger(__name__)


def _interest_id(interest: str) -> str:
    """Stable hash ID for an interest string (idempotent upserts)."""
    return "interest-" + hashlib.sha256(interest.encode()).hexdigest()[:12]


class AgendaRunner:
    """Scheduled autonomous task runner — superset of HeartbeatRunner.

    Processes system events (like HeartbeatRunner) AND executes
    scheduled agenda items (interests from ASSISTANT.md, standing instructions).
    Queues results and delivers them during timezone-aware active hours.
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
        self._delivery: DeliveryService | None = None
        # Track workflow IDs submitted by agenda (not user-initiated)
        self._agenda_workflows: set[str] = set()

    async def start(self) -> None:
        """Start the agenda loop as background task."""
        if not self._config.enabled:
            logger.debug("Agenda runner disabled, not starting")
            return
        self._sync_schedule()
        self._init_delivery()
        await self._sync_interests()
        self._subscribe_workflow_events()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Agenda runner started (interval=%.0fs)", self._config.interval_seconds
        )

    async def stop(self) -> None:
        """Cancel the agenda loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Agenda runner stopped")

    async def enqueue_event(self, event_type: str, data: dict | None = None) -> None:
        """Add system event for next tick to process (same as HeartbeatRunner)."""
        event_id = str(uuid.uuid4())
        data_json = json.dumps(data or {})
        await self._db.conn.execute(
            "INSERT INTO heartbeat_events (id, type, data) VALUES (?, ?, ?)",
            (event_id, event_type, data_json),
        )
        await self._db.conn.commit()

    def _sync_schedule(self) -> None:
        """Sync schedule from ASSISTANT.md into HeartbeatConfig fields."""
        schedule = parse_schedule(self._engine.assistant_text)
        if not schedule:
            return

        if tz := schedule.get("timezone"):
            self._config.timezone = tz
        if active := schedule.get("active_hours"):
            parts = active.split("-")
            if len(parts) == 2:
                try:
                    start_str = parts[0].strip().split(":")[0]
                    end_str = parts[1].strip().split(":")[0]
                    self._config.active_hours_start = int(start_str)
                    self._config.active_hours_end = int(end_str)
                except (ValueError, IndexError):
                    pass
        if channel := schedule.get("delivery_channel"):
            self._config.delivery_channel = channel
        if owner := schedule.get("owner_id"):
            self._config.owner_id = owner

        logger.info(
            "Schedule synced from ASSISTANT.md: tz=%s, active=%d-%d, channel=%s",
            self._config.timezone,
            self._config.active_hours_start,
            self._config.active_hours_end,
            self._config.delivery_channel,
        )

    def _init_delivery(self) -> None:
        """Initialize the delivery service."""
        self._delivery = DeliveryService(
            db=self._db,
            channels=self._channels,
            tz_name=self._config.timezone,
            active_start=self._config.active_hours_start,
            active_end=self._config.active_hours_end,
        )

    async def _loop(self) -> None:
        """Main loop — process events then agenda on each tick."""
        try:
            while True:
                await asyncio.sleep(self._config.interval_seconds)
                if not self._is_active_hours():
                    logger.debug("Outside active hours, skipping agenda tick")
                    # Still try to deliver pending results when hours resume
                    if self._delivery:
                        try:
                            await self._delivery.deliver_pending()
                        except Exception:
                            logger.exception("Delivery tick failed")
                    continue
                try:
                    await self._tick()
                except Exception:
                    logger.exception("Agenda tick failed")
        except asyncio.CancelledError:
            return

    async def _tick(self) -> None:
        """Single tick: process events, agenda items, then deliver pending."""
        await self._process_events()
        await self._process_agenda()
        if self._delivery:
            await self._delivery.deliver_pending()

    async def _process_events(self) -> None:
        """Poll and process pending heartbeat events (same logic as HeartbeatRunner)."""
        cursor = await self._db.conn.execute(
            "SELECT id, type, data FROM heartbeat_events "
            "WHERE processed = 0 ORDER BY created_at LIMIT 20"
        )
        rows = await cursor.fetchall()

        if not rows:
            return

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

        try:
            workflow_id = await self._engine.submit(prompt)
            logger.info(
                "Agenda events submitted workflow %s for %d events",
                workflow_id[:8], len(rows),
            )
        except Exception:
            logger.exception("Agenda runner failed to submit event workflow")
            return

        now = datetime.now(timezone.utc).isoformat()
        for eid in event_ids:
            await self._db.conn.execute(
                "UPDATE heartbeat_events SET processed = 1, processed_at = ? WHERE id = ?",
                (now, eid),
            )
        await self._db.conn.commit()

    async def _process_agenda(self) -> None:
        """Check and execute due agenda items."""
        now = datetime.now(timezone.utc)

        cursor = await self._db.conn.execute(
            "SELECT id, schedule, instruction, permission, last_run_at, run_count "
            "FROM agenda_items WHERE enabled = 1"
        )
        rows = await cursor.fetchall()

        for row in rows:
            last_run = None
            if row["last_run_at"]:
                try:
                    last_run = datetime.fromisoformat(row["last_run_at"])
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass

            if not is_due(row["schedule"], last_run, now):
                continue

            permission = row["permission"]
            if permission in ("write", "admin"):
                logger.warning(
                    "Skipping agenda item %s — requires '%s' permission",
                    row["id"], permission,
                )
                continue

            # Execute the agenda item
            try:
                workflow_id = await self._engine.submit(row["instruction"])
                self._agenda_workflows.add(workflow_id)
                logger.info(
                    "Agenda item %s submitted workflow %s",
                    row["id"], workflow_id[:8],
                )

                # Update run metadata
                nr = next_run(row["schedule"], now)
                await self._db.conn.execute(
                    "UPDATE agenda_items SET last_run_at = ?, next_run_at = ?, "
                    "run_count = ?, last_workflow_id = ?, updated_at = ? WHERE id = ?",
                    (
                        now.isoformat(),
                        nr.isoformat() if nr else None,
                        row["run_count"] + 1,
                        workflow_id,
                        now.isoformat(),
                        row["id"],
                    ),
                )
                await self._db.conn.commit()
            except Exception:
                logger.exception("Failed to execute agenda item %s", row["id"])

    async def _sync_interests(self) -> None:
        """Sync interests from ASSISTANT.md into agenda_items (idempotent)."""
        interests = parse_interests(self._engine.assistant_text)
        if not interests:
            return

        now = datetime.now(timezone.utc).isoformat()
        default_schedule = "every 6h"

        for interest in interests:
            item_id = _interest_id(interest)
            instruction = (
                f"Research and summarize recent developments on: {interest}. "
                f"Focus on what's new, notable, or actionable."
            )

            # Upsert: insert or update instruction (interest text may have changed)
            cursor = await self._db.conn.execute(
                "SELECT id FROM agenda_items WHERE id = ?", (item_id,)
            )
            existing = await cursor.fetchone()

            if existing:
                await self._db.conn.execute(
                    "UPDATE agenda_items SET instruction = ?, updated_at = ? WHERE id = ?",
                    (instruction, now, item_id),
                )
            else:
                await self._db.conn.execute(
                    "INSERT INTO agenda_items "
                    "(id, source, schedule, instruction, permission, "
                    "enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (item_id, "assistant_md", default_schedule, instruction, "read", now, now),
                )

        await self._db.conn.commit()
        logger.info("Synced %d interests from ASSISTANT.md to agenda", len(interests))

    def _is_active_hours(self) -> bool:
        """Check if current time is within active hours (timezone-aware).

        Uses DeliveryService's timezone-aware check if available,
        otherwise falls back to legacy quiet_hours logic.
        """
        if self._delivery:
            return self._delivery.is_active_hours()

        # Legacy fallback: quiet hours (inverse of active hours)
        start = self._config.quiet_hours_start
        end = self._config.quiet_hours_end
        if start is None or end is None:
            return True
        now_hour = datetime.now().hour
        if start <= end:
            return not (start <= now_hour < end)
        else:
            return not (now_hour >= start or now_hour < end)

    def _subscribe_workflow_events(self) -> None:
        """Auto-enqueue workflow completion/failure events."""
        self._engine.events.on("workflow.completed", self._on_workflow_event)
        self._engine.events.on("workflow.failed", self._on_workflow_event)

    async def _on_workflow_event(self, event: Event) -> None:
        """Handle workflow events: enqueue for processing + queue delivery for agenda items."""
        await self.enqueue_event(event.type, event.data)

        # If this was an agenda-submitted workflow, queue the result for delivery
        workflow_id = event.data.get("workflow_id", "")
        if workflow_id and workflow_id in self._agenda_workflows:
            self._agenda_workflows.discard(workflow_id)
            await self._queue_agenda_result(workflow_id, event)

    async def _queue_agenda_result(self, workflow_id: str, event: Event) -> None:
        """Fetch last step output and queue for delivery."""
        if not self._delivery:
            return
        if not self._config.delivery_channel or not self._config.owner_id:
            logger.debug("No delivery channel/owner configured, skipping result delivery")
            return

        # Fetch the last step's output
        try:
            cursor = await self._db.conn.execute(
                "SELECT output_data FROM steps WHERE workflow_id = ? "
                "ORDER BY ordinal DESC LIMIT 1",
                (workflow_id,),
            )
            row = await cursor.fetchone()
            if not row or not row["output_data"]:
                return

            body = row["output_data"]
            if len(body) > 4000:
                body = body[:4000] + "\n\n[truncated]"

            await self._delivery.queue_result(
                workflow_id=workflow_id,
                body=body,
                channel=self._config.delivery_channel,
                recipient_id=self._config.owner_id,
                subject=f"Research complete (workflow {workflow_id[:8]})",
            )
        except Exception:
            logger.exception("Failed to queue agenda result for %s", workflow_id[:8])
