"""Tests for channel permission model, RestrictedEngine proxy, and rate limiting."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.channels.context import ChannelContext
from openhydra.channels.permissions import ChannelPermissions
from openhydra.channels.restricted_engine import RestrictedEngine, _RestrictedEventBus


class TestChannelPermissions:
    def test_full_access(self):
        perms = ChannelPermissions.full_access()
        assert perms.can_submit is True
        assert perms.can_read_status is True
        assert perms.can_access_sessions is True
        assert perms.can_emit_events is True
        assert perms.can_access_db is True
        assert perms.max_submissions_per_hour == 0

    def test_restricted_defaults(self):
        perms = ChannelPermissions.restricted()
        assert perms.can_submit is True
        assert perms.can_read_status is True
        assert perms.can_access_sessions is True
        assert perms.can_emit_events is False
        assert perms.can_access_db is False
        assert perms.max_submissions_per_hour == 10

    def test_restricted_with_overrides(self):
        perms = ChannelPermissions.restricted({
            "can_emit_events": True,
            "max_submissions_per_hour": 50,
        })
        assert perms.can_emit_events is True
        assert perms.max_submissions_per_hour == 50
        # Other defaults unchanged
        assert perms.can_access_db is False

    def test_restricted_ignores_unknown_keys(self):
        perms = ChannelPermissions.restricted({"unknown_field": True})
        assert not hasattr(perms, "unknown_field")

    def test_default_permissions(self):
        perms = ChannelPermissions()
        assert perms.can_submit is True
        assert perms.can_emit_events is False
        assert perms.can_access_db is False


class TestRestrictedEngine:
    @pytest.fixture
    def engine(self):
        eng = MagicMock()
        eng.submit = AsyncMock(return_value="wf-123")
        eng.get_status = AsyncMock(return_value={"status": "completed"})
        eng.list_workflows = AsyncMock(return_value=[])
        eng.approve = AsyncMock()
        eng.reject = AsyncMock()
        eng.pause = AsyncMock()
        eng.resume = AsyncMock(return_value="wf-123")
        eng.cancel = AsyncMock()
        eng.events = MagicMock()
        eng.db = MagicMock()
        eng.config = MagicMock()
        return eng

    def test_config_always_accessible(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        assert proxy.config is engine.config

    @pytest.mark.asyncio
    async def test_submit_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        wf_id = await proxy.submit("do something")
        assert wf_id == "wf-123"
        engine.submit.assert_called_once_with("do something")

    @pytest.mark.asyncio
    async def test_submit_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="submit"):
            await proxy.submit("do something")
        engine.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_status_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        result = await proxy.get_status("wf-123")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_status_denied(self, engine):
        perms = ChannelPermissions(can_read_status=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="status"):
            await proxy.get_status("wf-123")

    @pytest.mark.asyncio
    async def test_list_workflows_denied(self, engine):
        perms = ChannelPermissions(can_read_status=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="status"):
            await proxy.list_workflows()

    def test_db_access_denied(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="database"):
            _ = proxy.db

    def test_db_access_allowed(self, engine):
        perms = ChannelPermissions(can_access_db=True)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        assert proxy.db is engine.db

    def test_events_restricted_subscribe_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        events = proxy.events
        assert isinstance(events, _RestrictedEventBus)
        handler = MagicMock()
        events.on("test.event", handler)
        engine.events.on.assert_called_once_with("test.event", handler)

    @pytest.mark.asyncio
    async def test_events_restricted_emit_blocked(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        events = proxy.events
        with pytest.raises(PermissionError, match="emit"):
            await events.emit(MagicMock(type="test.event"))

    def test_events_full_access(self, engine):
        perms = ChannelPermissions(can_emit_events=True)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        assert proxy.events is engine.events

    def test_unknown_attribute_blocked(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="workflow_engine"):
            _ = proxy.workflow_engine

    @pytest.mark.asyncio
    async def test_approve_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        await proxy.approve("ap-1")
        engine.approve.assert_called_once_with("ap-1")

    @pytest.mark.asyncio
    async def test_approve_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="approve"):
            await proxy.approve("ap-1")
        engine.approve.assert_not_called()

    @pytest.mark.asyncio
    async def test_reject_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        await proxy.reject("ap-1", "bad")
        engine.reject.assert_called_once_with("ap-1", "bad")

    @pytest.mark.asyncio
    async def test_reject_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="reject"):
            await proxy.reject("ap-1")
        engine.reject.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        await proxy.pause("wf-1")
        engine.pause.assert_called_once_with("wf-1", paused_by="")

    @pytest.mark.asyncio
    async def test_pause_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="pause"):
            await proxy.pause("wf-1")
        engine.pause.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        result = await proxy.resume("wf-1")
        assert result == "wf-123"
        engine.resume.assert_called_once_with("wf-1")

    @pytest.mark.asyncio
    async def test_resume_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="resume"):
            await proxy.resume("wf-1")
        engine.resume.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_allowed(self, engine):
        perms = ChannelPermissions.restricted()
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        await proxy.cancel("wf-1")
        engine.cancel.assert_called_once_with("wf-1")

    @pytest.mark.asyncio
    async def test_cancel_denied(self, engine):
        perms = ChannelPermissions(can_submit=False)
        proxy = RestrictedEngine(engine, perms, "test-plugin")
        with pytest.raises(PermissionError, match="cancel"):
            await proxy.cancel("wf-1")
        engine.cancel.assert_not_called()


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_enforced(self, ):
        engine = MagicMock()
        engine.submit = AsyncMock(return_value="wf-x")
        perms = ChannelPermissions(max_submissions_per_hour=3)
        proxy = RestrictedEngine(engine, perms, "rate-test")

        # First 3 should succeed
        for _ in range(3):
            await proxy.submit("task")

        # 4th should fail
        with pytest.raises(PermissionError, match="rate limit"):
            await proxy.submit("one more")

    @pytest.mark.asyncio
    async def test_rate_limit_sliding_window(self):
        engine = MagicMock()
        engine.submit = AsyncMock(return_value="wf-x")
        perms = ChannelPermissions(max_submissions_per_hour=2)
        proxy = RestrictedEngine(engine, perms, "rate-test")

        # Submit 2
        await proxy.submit("a")
        await proxy.submit("b")

        # Manually expire old entries by setting their times in the past
        proxy._submit_times.clear()
        proxy._submit_times.append(time.monotonic() - 7200)  # 2 hours ago

        # Should succeed because old entry is pruned
        await proxy.submit("c")

    @pytest.mark.asyncio
    async def test_unlimited_rate(self):
        engine = MagicMock()
        engine.submit = AsyncMock(return_value="wf-x")
        perms = ChannelPermissions(max_submissions_per_hour=0)
        proxy = RestrictedEngine(engine, perms, "unlimited")

        # Should never hit rate limit
        for _ in range(100):
            await proxy.submit("task")
        assert engine.submit.call_count == 100


class TestChannelContext:
    def test_context_with_permissions(self):
        perms = ChannelPermissions.restricted()
        ctx = ChannelContext(engine=MagicMock(), permissions=perms)
        assert ctx.permissions.can_access_db is False
        assert ctx.permissions.can_emit_events is False

    def test_context_default_full_access(self):
        ctx = ChannelContext(engine=MagicMock())
        assert ctx.permissions.can_access_db is True
        assert ctx.permissions.can_emit_events is True
