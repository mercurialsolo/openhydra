"""DeliveryService — queues and delivers autonomous task results during active hours."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.db import Database

logger = logging.getLogger(__name__)


class DeliveryService:
    """Queue results from autonomous tasks and deliver during active hours.

    Messages are batched per (channel, recipient) when multiple are pending.
    Delivery respects timezone-aware active hours.
    """

    def __init__(
        self,
        db: Database,
        channels: dict[str, Channel],
        *,
        tz_name: str = "",
        active_start: int = 8,
        active_end: int = 22,
    ) -> None:
        self._db = db
        self._channels = channels
        self._tz_name = tz_name
        self._active_start = active_start
        self._active_end = active_end

    async def queue_result(
        self,
        workflow_id: str,
        body: str,
        channel: str,
        recipient_id: str,
        subject: str = "",
        priority: str = "normal",
    ) -> str:
        """Insert a delivery item into the queue. Returns the delivery ID."""
        delivery_id = str(uuid.uuid4())
        await self._db.conn.execute(
            "INSERT INTO delivery_queue "
            "(id, workflow_id, recipient_channel, recipient_id, subject, body, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (delivery_id, workflow_id, channel, recipient_id, subject, body, priority),
        )
        await self._db.conn.commit()
        logger.info(
            "Queued delivery %s for %s:%s (workflow %s)",
            delivery_id[:8], channel, recipient_id, workflow_id[:8],
        )
        return delivery_id

    async def deliver_pending(self) -> int:
        """Deliver all pending messages if within active hours.

        Returns the number of messages delivered.
        """
        if not self.is_active_hours():
            logger.debug("Outside active hours, skipping delivery")
            return 0

        cursor = await self._db.conn.execute(
            "SELECT id, workflow_id, recipient_channel, recipient_id, subject, body "
            "FROM delivery_queue WHERE status = 'pending' "
            "ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        if not rows:
            return 0

        # Group by (channel, recipient) for batching
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in rows:
            key = (row["recipient_channel"], row["recipient_id"])
            groups[key].append({
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "subject": row["subject"],
                "body": row["body"],
            })

        delivered = 0
        now = datetime.now(timezone.utc).isoformat()

        for (channel_name, recipient_id), items in groups.items():
            ch = self._channels.get(channel_name)
            if not ch:
                logger.warning(
                    "Delivery channel '%s' not available, skipping %d items",
                    channel_name, len(items),
                )
                continue

            # Build message (batch if multiple)
            if len(items) == 1:
                text = items[0]["body"]
            else:
                parts = []
                for i, item in enumerate(items, 1):
                    label = item["subject"] or f"Update {i}"
                    parts.append(f"{i}. **{label}**\n{item['body']}")
                text = "Here are your updates:\n\n" + "\n\n".join(parts)

            try:
                await ch.send_message(recipient_id, text)
                # Mark all items as delivered
                for item in items:
                    await self._db.conn.execute(
                        "UPDATE delivery_queue SET status = 'delivered', "
                        "delivered_at = ? WHERE id = ?",
                        (now, item["id"]),
                    )
                delivered += len(items)
                logger.info(
                    "Delivered %d items to %s:%s",
                    len(items), channel_name, recipient_id,
                )
            except Exception:
                logger.exception(
                    "Failed to deliver to %s:%s", channel_name, recipient_id
                )

        if delivered:
            await self._db.conn.commit()
        return delivered

    def is_active_hours(self) -> bool:
        """Check if current time is within active hours (timezone-aware)."""
        if self._tz_name:
            try:
                tz = ZoneInfo(self._tz_name)
            except (KeyError, ValueError):
                logger.warning("Invalid timezone '%s', using UTC", self._tz_name)
                tz = timezone.utc
        else:
            tz = timezone.utc

        now_hour = datetime.now(tz).hour
        start = self._active_start
        end = self._active_end

        if start <= end:
            return start <= now_hour < end
        else:
            # Wraps midnight (e.g. 22-6)
            return now_hour >= start or now_hour < end
