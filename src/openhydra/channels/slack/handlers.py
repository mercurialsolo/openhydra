"""Slack event and action handlers — wire bolt app to Engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .formatters import event_to_blocks, event_to_color, event_to_text

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp

    from openhydra.channels.access import AccessControl
    from openhydra.channels.context import ChannelContext
    from openhydra.events import Event

logger = logging.getLogger(__name__)


class SlackHandlers:
    """Registers Slack listeners and routes them to Engine operations."""

    def __init__(
        self,
        bolt_app: AsyncApp,
        ctx: ChannelContext,
        access: AccessControl,
    ) -> None:
        self._app = bolt_app
        self._engine = ctx.engine
        self._sessions = ctx.sessions
        self._debouncer = ctx.debouncer
        self._access = access
        # Fallback in-memory map when no session store
        self._threads: dict[str, tuple[str, str]] = {}

    async def _check_access(self, user_id: str, say=None) -> bool:
        """Check if user is allowed — delegates to AccessControl."""
        async def notify(msg: str) -> None:
            if say:
                await say(msg)

        return await self._access.check_and_notify("slack", user_id, notify_fn=notify)

    def register(self) -> None:
        """Register all Slack event/action handlers and subscribe to engine events."""

        @self._app.event("app_mention")
        async def handle_mention(event: dict[str, Any], say) -> None:
            await self._handle_task(event, say)

        @self._app.event("message")
        async def handle_dm(event: dict[str, Any], say) -> None:
            # Only handle DMs (no subtype = plain message, channel_type = im)
            if event.get("channel_type") == "im" and not event.get("subtype"):
                await self._handle_task(event, say)

        @self._app.action("approve")
        async def handle_approve(ack, action, say) -> None:
            await ack()
            approval_id = action["value"]
            await self._engine.approve(approval_id)
            await say(f":white_check_mark: Approved `{approval_id}`")

        @self._app.action("reject")
        async def handle_reject(ack, action, say) -> None:
            await ack()
            approval_id = action["value"]
            await self._engine.reject(approval_id, "Rejected via Slack")
            await say(f":x: Rejected `{approval_id}`")

        @self._app.action("pause_wf")
        async def handle_pause(ack, action, say) -> None:
            await ack()
            wf_id = action["value"]
            await self._engine.pause(wf_id)
            await say(f":double_vertical_bar: Paused workflow `{wf_id[:8]}`")

        @self._app.action("resume_wf")
        async def handle_resume(ack, action, say) -> None:
            await ack()
            wf_id = action["value"]
            await self._engine.resume(wf_id)
            await say(f":arrow_forward: Resumed workflow `{wf_id[:8]}`")

        @self._app.action("cancel_wf")
        async def handle_cancel(ack, action, say) -> None:
            await ack()
            wf_id = action["value"]
            await self._engine.cancel(wf_id)
            await say(f":octagonal_sign: Cancelled workflow `{wf_id[:8]}`")

        # Subscribe to engine events via EventBus
        self._engine.events.on_all(self.on_engine_event)

    async def _handle_task(self, event: dict[str, Any], say) -> None:
        """Parse a task from a Slack message and submit to engine."""
        user_id = event.get("user", "")
        if not await self._check_access(user_id, say=say):
            return

        text = event.get("text", "").strip()
        # Strip bot mention (e.g. "<@U12345> do something" → "do something")
        if text.startswith("<@"):
            text = text.split(">", 1)[-1].strip()

        if not text:
            await say("Please provide a task description.")
            return

        # Debounce if configured
        if self._debouncer:
            combined = await self._debouncer.debounce(f"slack:{user_id}", text)
            if combined is None:
                return
            text = combined

        channel = event.get("channel", "")
        thread_ts = event.get("ts", "")

        workflow_id = await self._engine.submit(
            text,
            session_key=f"slack:{user_id}",
            channel="slack",
            user_id=user_id,
        )

        # Store in session if available, else fallback to in-memory
        if self._sessions:
            from openhydra.channels.session import ChannelSession

            session_key = f"slack:{user_id}"
            session = ChannelSession(
                session_key=session_key,
                active_workflow_id=workflow_id,
                last_channel="slack",
                last_message_at=datetime.now(timezone.utc),
                metadata={"channel": channel, "thread_ts": thread_ts},
            )
            await self._sessions.upsert(session)
        self._threads[workflow_id] = (channel, thread_ts)

        await say(
            text=f":rocket: Workflow `{workflow_id[:8]}` started for: {text}",
            thread_ts=thread_ts,
        )

    async def on_engine_event(self, event: Event) -> None:
        """Forward engine events to the appropriate Slack thread."""
        wf_id = event.data.get("workflow_id", "")

        # Try session store first, fallback to in-memory
        thread_info = self._threads.get(wf_id)
        if not thread_info and self._sessions:
            session = await self._sessions.find_by_workflow(wf_id)
            if session and session.last_channel == "slack":
                ch = session.metadata.get("channel", "")
                ts = session.metadata.get("thread_ts", "")
                if ch:
                    thread_info = (ch, ts)

        if not thread_info:
            return

        channel, thread_ts = thread_info
        blocks = event_to_blocks(event)
        text = event_to_text(event)

        try:
            await self._app.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
                blocks=blocks,
                attachments=[{"color": event_to_color(event), "blocks": []}],
            )
        except Exception:
            logger.exception("Failed to post Slack message for event %s", event.type)

        # Cleanup thread mapping when workflow finishes
        if event.type in ("workflow.completed", "workflow.failed", "workflow.cancelled"):
            self._threads.pop(wf_id, None)
            if self._sessions:
                await self._sessions.clear_workflow(wf_id)

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a direct message to a Slack user."""
        try:
            resp = await self._app.client.conversations_open(users=user_id)
            channel_id = resp["channel"]["id"]
            await self._app.client.chat_postMessage(channel=channel_id, text=text)
        except Exception:
            logger.exception("Failed to send Slack DM to %s", user_id)
