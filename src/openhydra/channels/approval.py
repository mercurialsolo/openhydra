"""Approval manager — routes approval requests to users via their active channels."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openhydra.channels.base import Channel
    from openhydra.channels.session import SessionStore
    from openhydra.engine import Engine
    from openhydra.events import Event

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Bridges APPROVAL_REQUESTED events to user channels with timeout."""

    def __init__(
        self,
        engine: Engine,
        sessions: SessionStore,
        channels: dict[str, Channel],
        default_timeout: float = 120.0,
        timeout_action: str = "reject",
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._channels = channels
        self._default_timeout = default_timeout
        self._timeout_action = timeout_action
        self._timeout_tasks: dict[str, asyncio.Task] = {}

    def start(self) -> None:
        """Subscribe to APPROVAL_REQUESTED events."""
        self._engine.events.on("approval.requested", self._on_approval_requested)

    def stop(self) -> None:
        """Cancel timeout tasks and unsubscribe."""
        for task in self._timeout_tasks.values():
            task.cancel()
        self._timeout_tasks.clear()
        self._engine.events.off("approval.requested", self._on_approval_requested)

    async def _on_approval_requested(self, event: Event) -> None:
        """Find user's active channel via session store, send prompt, start timeout."""
        workflow_id = event.data.get("workflow_id", "")
        approval_id = event.data.get("approval_id", "")
        prompt = event.data.get("prompt", "Approval required.")

        if not workflow_id:
            return

        session = await self._sessions.find_by_workflow(workflow_id)
        if not session:
            logger.debug("No session found for workflow %s, cannot route approval", workflow_id)
            return

        channel_name = session.last_channel
        channel = self._channels.get(channel_name)
        if not channel:
            logger.warning("Channel '%s' not found for approval routing", channel_name)
            return

        # Extract user_id from session_key ("{channel}:{user_id}")
        parts = session.session_key.split(":", 1)
        user_id = parts[1] if len(parts) > 1 else session.session_key

        # Send the approval prompt
        message = (
            f"Approval needed for workflow {workflow_id[:8]}:\n"
            f"{prompt}\n\nReply 'approve' or 'reject'."
        )
        try:
            await channel.send_message(user_id, message)
        except Exception:
            logger.exception("Failed to send approval prompt to %s via %s", user_id, channel_name)
            return

        # Start timeout
        if approval_id:
            task = asyncio.create_task(
                self._timeout_approval(approval_id, self._default_timeout)
            )
            self._timeout_tasks[approval_id] = task

    async def _timeout_approval(self, approval_id: str, timeout: float) -> None:
        """Auto-reject/approve after timeout."""
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return

        self._timeout_tasks.pop(approval_id, None)

        if self._timeout_action == "reject":
            logger.info("Approval %s timed out — auto-rejecting", approval_id)
            await self._engine.reject(approval_id, "Timed out — auto-rejected")
        elif self._timeout_action == "approve":
            logger.info("Approval %s timed out — auto-approving", approval_id)
            await self._engine.approve(approval_id)
        else:
            logger.info("Approval %s timed out — ignoring", approval_id)
