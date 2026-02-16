"""Tests for heartbeat runner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openhydra.config import HeartbeatConfig
from openhydra.db import Database
from openhydra.events import Event, EventBus
from openhydra.heartbeat.runner import HeartbeatRunner


class FakeEngine:
    def __init__(self):
        self.events = EventBus()
        self.submit = AsyncMock(return_value="wf-heartbeat")
        self.db = None


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.mark.asyncio
async def test_disabled_by_default(engine, db):
    config = HeartbeatConfig(enabled=False)
    runner = HeartbeatRunner(engine, db, config)
    await runner.start()
    assert runner._task is None
    await runner.stop()


@pytest.mark.asyncio
async def test_start_stop_lifecycle(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)
    await runner.start()
    assert runner._task is not None
    await runner.stop()
    assert runner._task is None


@pytest.mark.asyncio
async def test_enqueue_persists_to_db(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)

    await runner.enqueue_event("test.event", {"key": "val"})

    cursor = await db.conn.execute(
        "SELECT type, data, processed FROM heartbeat_events"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["type"] == "test.event"
    assert rows[0]["processed"] == 0


@pytest.mark.asyncio
async def test_tick_submits_when_events_pending(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)

    await runner.enqueue_event("workflow.completed", {"workflow_id": "wf-1"})
    await runner._tick()

    engine.submit.assert_called_once()
    prompt = engine.submit.call_args[0][0]
    assert "workflow.completed" in prompt


@pytest.mark.asyncio
async def test_tick_marks_events_processed(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)

    await runner.enqueue_event("test.event", {})
    await runner._tick()

    cursor = await db.conn.execute(
        "SELECT processed FROM heartbeat_events"
    )
    rows = await cursor.fetchall()
    assert all(r["processed"] == 1 for r in rows)


@pytest.mark.asyncio
async def test_tick_skips_when_no_events(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)

    await runner._tick()
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_quiet_hours_skips(engine, db):
    from datetime import datetime
    from unittest.mock import patch

    config = HeartbeatConfig(
        enabled=True,
        interval_seconds=100,
        quiet_hours_start=22,
        quiet_hours_end=6,
    )
    runner = HeartbeatRunner(engine, db, config)

    # Mock time to be in quiet hours
    with patch("openhydra.heartbeat.runner.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 23, 0)  # 11 PM
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert runner._is_quiet_hours()

    # Mock time to be outside quiet hours
    with patch("openhydra.heartbeat.runner.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2024, 1, 1, 12, 0)  # noon
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        assert not runner._is_quiet_hours()


@pytest.mark.asyncio
async def test_workflow_event_auto_enqueued(engine, db):
    config = HeartbeatConfig(enabled=True, interval_seconds=100)
    runner = HeartbeatRunner(engine, db, config)
    await runner.start()

    # Emit a workflow completed event
    event = Event(type="workflow.completed", data={"workflow_id": "wf-done"})
    await engine.events.emit(event)

    # Check it was enqueued
    cursor = await db.conn.execute(
        "SELECT type FROM heartbeat_events WHERE processed = 0"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["type"] == "workflow.completed"

    await runner.stop()
