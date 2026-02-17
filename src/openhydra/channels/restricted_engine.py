"""RestrictedEngine — security proxy that wraps Engine for external channel plugins."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhydra.channels.permissions import ChannelPermissions
    from openhydra.engine import Engine

logger = logging.getLogger(__name__)


class _RestrictedEventBus:
    """Event bus proxy that allows subscribe but blocks emit."""

    def __init__(self, real_bus: Any, channel_name: str) -> None:
        self._bus = real_bus
        self._channel_name = channel_name

    def on(self, event_type: str, handler: Any) -> None:
        self._bus.on(event_type, handler)

    def on_all(self, handler: Any) -> None:
        self._bus.on_all(handler)

    def off(self, event_type: str, handler: Any) -> None:
        self._bus.off(event_type, handler)

    async def emit(self, event: Any) -> None:
        logger.warning(
            "Channel '%s' blocked from emitting event '%s'",
            self._channel_name, getattr(event, "type", "unknown"),
        )
        raise PermissionError(
            f"Channel '{self._channel_name}' does not have permission to emit events"
        )


class RestrictedEngine:
    """Proxy around Engine that enforces per-channel permissions.

    Bundled channels get the real Engine; external plugins get this proxy
    which checks permission flags before delegating to the real engine.
    """

    def __init__(
        self,
        engine: Engine,
        permissions: ChannelPermissions,
        channel_name: str,
    ) -> None:
        self._engine = engine
        self._permissions = permissions
        self._channel_name = channel_name
        # Sliding window for rate limiting (timestamps of recent submissions)
        self._submit_times: deque[float] = deque()

    @property
    def config(self) -> Any:
        return self._engine.config

    @property
    def events(self) -> Any:
        if self._permissions.can_emit_events:
            return self._engine.events
        return _RestrictedEventBus(self._engine.events, self._channel_name)

    @property
    def db(self) -> Any:
        if not self._permissions.can_access_db:
            logger.warning(
                "Channel '%s' denied access to database", self._channel_name
            )
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have database access"
            )
        return self._engine.db

    async def submit(self, task: str) -> str:
        if not self._permissions.can_submit:
            logger.warning(
                "Channel '%s' denied submit permission", self._channel_name
            )
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have submit permission"
            )
        self._check_rate_limit()
        result = await self._engine.submit(task)
        self._submit_times.append(time.monotonic())
        return result

    async def get_status(self, workflow_id: str) -> dict[str, Any]:
        if not self._permissions.can_read_status:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have status read permission"
            )
        return await self._engine.get_status(workflow_id)

    async def list_workflows(self) -> list[dict[str, Any]]:
        if not self._permissions.can_read_status:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have status read permission"
            )
        return await self._engine.list_workflows()

    async def approve(self, approval_id: str) -> None:
        if not self._permissions.can_submit:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have permission to approve"
            )
        await self._engine.approve(approval_id)

    async def reject(self, approval_id: str, reason: str = "") -> None:
        if not self._permissions.can_submit:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have permission to reject"
            )
        await self._engine.reject(approval_id, reason)

    async def pause(self, workflow_id: str, paused_by: str = "") -> None:
        if not self._permissions.can_submit:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have permission to pause workflows"
            )
        await self._engine.pause(workflow_id, paused_by=paused_by)

    async def resume(self, workflow_id: str) -> str:
        if not self._permissions.can_submit:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have permission to resume workflows"
            )
        return await self._engine.resume(workflow_id)

    async def cancel(self, workflow_id: str) -> None:
        if not self._permissions.can_submit:
            raise PermissionError(
                f"Channel '{self._channel_name}' does not have permission to cancel workflows"
            )
        await self._engine.cancel(workflow_id)

    def _check_rate_limit(self) -> None:
        """Enforce max_submissions_per_hour with sliding window."""
        limit = self._permissions.max_submissions_per_hour
        if limit <= 0:
            return
        now = time.monotonic()
        cutoff = now - 3600
        # Purge old entries
        while self._submit_times and self._submit_times[0] < cutoff:
            self._submit_times.popleft()
        if len(self._submit_times) >= limit:
            logger.warning(
                "Channel '%s' rate limited (%d/%d submissions per hour)",
                self._channel_name, len(self._submit_times), limit,
            )
            raise PermissionError(
                f"Channel '{self._channel_name}' exceeded rate limit "
                f"({limit} submissions per hour)"
            )

    def __getattr__(self, name: str) -> Any:
        logger.warning(
            "Channel '%s' denied access to engine attribute '%s'",
            self._channel_name, name,
        )
        raise PermissionError(
            f"Channel '{self._channel_name}' does not have access to engine.{name}"
        )
