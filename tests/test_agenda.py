"""Tests for AgendaRunner."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.agenda.runner import AgendaRunner, _interest_id


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.assistant_text = "## Interests\n- AI safety\n- Rust ecosystem\n"
    engine.submit = AsyncMock(return_value="wf-123")
    engine.events = MagicMock()
    engine.events.on = MagicMock()
    return engine


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = AsyncMock()
    db.conn = conn
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    return db


@pytest.fixture
def config():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.interval_seconds = 60.0
    cfg.quiet_hours_start = None
    cfg.quiet_hours_end = None
    cfg.timezone = ""
    cfg.active_hours_start = 8
    cfg.active_hours_end = 22
    cfg.delivery_channel = ""
    cfg.owner_id = ""
    return cfg


class TestInterestId:
    def test_stable_hash(self):
        assert _interest_id("AI safety") == _interest_id("AI safety")

    def test_different_inputs_differ(self):
        assert _interest_id("AI safety") != _interest_id("Rust ecosystem")

    def test_prefix(self):
        assert _interest_id("test").startswith("interest-")


class TestAgendaRunnerInit:
    def test_constructor(self, mock_engine, mock_db, config):
        runner = AgendaRunner(mock_engine, mock_db, config)
        assert runner._engine is mock_engine
        assert runner._db is mock_db

    @pytest.mark.asyncio
    async def test_start_disabled(self, mock_engine, mock_db, config):
        config.enabled = False
        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner.start()
        assert runner._task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, mock_engine, mock_db, config):
        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner.stop()  # Should not raise


class TestSyncSchedule:
    def test_syncs_schedule_from_assistant(self, mock_engine, mock_db, config):
        mock_engine.assistant_text = (
            "## Schedule\n"
            "- timezone: America/New_York\n"
            "- active_hours: 9:00-21:00\n"
            "- delivery_channel: slack\n"
            "- owner_id: U99999\n"
        )
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._sync_schedule()

        assert config.timezone == "America/New_York"
        assert config.active_hours_start == 9
        assert config.active_hours_end == 21
        assert config.delivery_channel == "slack"
        assert config.owner_id == "U99999"

    def test_no_schedule_is_noop(self, mock_engine, mock_db, config):
        mock_engine.assistant_text = "No schedule section"
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._sync_schedule()
        assert config.timezone == ""

    def test_partial_schedule(self, mock_engine, mock_db, config):
        mock_engine.assistant_text = "## Schedule\n- timezone: UTC\n"
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._sync_schedule()
        assert config.timezone == "UTC"
        assert config.delivery_channel == ""  # unchanged


class TestSyncInterests:
    @pytest.mark.asyncio
    async def test_sync_creates_items(self, mock_engine, mock_db, config):
        # Mock: no existing items
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._sync_interests()

        # Should have called execute multiple times (selects + inserts + commit)
        assert mock_db.conn.execute.call_count >= 2
        assert mock_db.conn.commit.called

    @pytest.mark.asyncio
    async def test_sync_updates_existing(self, mock_engine, mock_db, config):
        # Mock: existing items
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value={"id": "existing"})
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._sync_interests()

        assert mock_db.conn.commit.called

    @pytest.mark.asyncio
    async def test_sync_no_interests(self, mock_engine, mock_db, config):
        mock_engine.assistant_text = "No interests section"
        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._sync_interests()

        # No DB writes expected
        assert not mock_db.conn.commit.called


class TestProcessEvents:
    @pytest.mark.asyncio
    async def test_no_events_is_noop(self, mock_engine, mock_db, config):
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._process_events()

        mock_engine.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_pending_events(self, mock_engine, mock_db, config):
        rows = [
            {"id": "e1", "type": "workflow.completed", "data": '{"id": "wf-1"}'},
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._process_events()

        mock_engine.submit.assert_called_once()


class TestProcessAgenda:
    @pytest.mark.asyncio
    async def test_executes_due_read_item(self, mock_engine, mock_db, config):
        rows = [
            {
                "id": "item-1",
                "schedule": "every 6h",
                "instruction": "Research AI",
                "permission": "read",
                "last_run_at": None,
                "run_count": 0,
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._process_agenda()

        mock_engine.submit.assert_called_once_with("Research AI")
        # Should track the workflow as agenda-submitted
        assert "wf-123" in runner._agenda_workflows

    @pytest.mark.asyncio
    async def test_skips_write_permission(self, mock_engine, mock_db, config):
        rows = [
            {
                "id": "item-2",
                "schedule": "every 6h",
                "instruction": "Deploy code",
                "permission": "write",
                "last_run_at": None,
                "run_count": 0,
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._process_agenda()

        mock_engine.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_not_due(self, mock_engine, mock_db, config):
        now = datetime.now(timezone.utc)
        rows = [
            {
                "id": "item-3",
                "schedule": "every 6h",
                "instruction": "Check updates",
                "permission": "read",
                "last_run_at": now.isoformat(),  # just ran
                "run_count": 1,
            },
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.conn.execute = AsyncMock(return_value=cursor)

        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner._process_agenda()

        mock_engine.submit.assert_not_called()


class TestEnqueueEvent:
    @pytest.mark.asyncio
    async def test_inserts_event(self, mock_engine, mock_db, config):
        runner = AgendaRunner(mock_engine, mock_db, config)
        await runner.enqueue_event("test.event", {"key": "value"})

        mock_db.conn.execute.assert_called_once()
        args = mock_db.conn.execute.call_args[0]
        assert "INSERT INTO heartbeat_events" in args[0]
        assert mock_db.conn.commit.called


class TestActiveHours:
    def test_with_delivery_service(self, mock_engine, mock_db, config):
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = MagicMock()
        runner._delivery.is_active_hours.return_value = True
        assert runner._is_active_hours() is True

        runner._delivery.is_active_hours.return_value = False
        assert runner._is_active_hours() is False

    def test_legacy_fallback_no_quiet_hours(self, mock_engine, mock_db, config):
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = None
        assert runner._is_active_hours() is True

    def test_legacy_fallback_within_quiet_hours(self, mock_engine, mock_db, config):
        config.quiet_hours_start = 0
        config.quiet_hours_end = 24
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = None
        assert runner._is_active_hours() is False


class TestWorkflowEventDelivery:
    @pytest.mark.asyncio
    async def test_agenda_workflow_queued_for_delivery(self, mock_engine, mock_db, config):
        config.delivery_channel = "slack"
        config.owner_id = "U12345"
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = MagicMock()
        runner._delivery.queue_result = AsyncMock()

        # Simulate agenda workflow
        runner._agenda_workflows.add("wf-completed")

        # Mock step output
        step_cursor = AsyncMock()
        step_cursor.fetchone = AsyncMock(return_value={"output_data": "Research results"})
        mock_db.conn.execute = AsyncMock(return_value=step_cursor)

        event = MagicMock()
        event.type = "workflow.completed"
        event.data = {"workflow_id": "wf-completed"}

        await runner._on_workflow_event(event)

        runner._delivery.queue_result.assert_called_once()
        args = runner._delivery.queue_result.call_args[1]
        assert args["workflow_id"] == "wf-completed"
        assert args["body"] == "Research results"
        assert args["channel"] == "slack"
        assert args["recipient_id"] == "U12345"

        # Should be removed from tracking set
        assert "wf-completed" not in runner._agenda_workflows

    @pytest.mark.asyncio
    async def test_non_agenda_workflow_not_delivered(self, mock_engine, mock_db, config):
        config.delivery_channel = "slack"
        config.owner_id = "U12345"
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = MagicMock()
        runner._delivery.queue_result = AsyncMock()

        event = MagicMock()
        event.type = "workflow.completed"
        event.data = {"workflow_id": "wf-user-initiated"}

        await runner._on_workflow_event(event)

        runner._delivery.queue_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_delivery_when_no_channel_configured(self, mock_engine, mock_db, config):
        config.delivery_channel = ""
        config.owner_id = ""
        runner = AgendaRunner(mock_engine, mock_db, config)
        runner._delivery = MagicMock()
        runner._delivery.queue_result = AsyncMock()
        runner._agenda_workflows.add("wf-x")

        event = MagicMock()
        event.type = "workflow.completed"
        event.data = {"workflow_id": "wf-x"}

        await runner._on_workflow_event(event)

        runner._delivery.queue_result.assert_not_called()
