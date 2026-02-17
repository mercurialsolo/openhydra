"""Tests for workflow pause/resume/cancel, auto-resume, step timeout, and progress events."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.db import Database
from openhydra.events import (
    STEP_PROGRESS,
    STEP_TIMEOUT,
    WORKFLOW_CANCELLED,
    WORKFLOW_PAUSED,
    WORKFLOW_RESUMED,
    Event,
    EventBus,
)
from openhydra.roles.catalog import BudgetConfig, RoleCatalog
from openhydra.workflow.engine import WorkflowEngine
from openhydra.workflow.models import Step, StepStatus, WorkflowStatus


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "roles.yaml")
    return catalog


@pytest.fixture
def events() -> EventBus:
    return EventBus()


def _make_result(text: str = "done") -> SessionResult:
    return SessionResult(
        output={"text": text, "quality_score": 30},
        raw_text=text,
        tokens_used=100,
        cost_usd=0.01,
    )


@pytest.fixture
def mock_executor() -> AsyncMock:
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=_make_result())
    return executor


@pytest.fixture
async def engine(
    db: Database, events: EventBus, mock_executor: AsyncMock, roles: RoleCatalog,
):
    return WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
        max_retries=2, max_concurrent=2,
    )


# --- Pause ---


async def test_pause_running_workflow(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """Pause after step 0 starts; step 0 finishes, step 1 stays pending."""
    step_gate = asyncio.Event()
    call_count = 0

    async def slow_executor(role_id, instructions, context=None, messages=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            step_gate.set()  # signal that step 0 is executing
            await asyncio.sleep(0.05)
        return _make_result()

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=slow_executor)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        max_retries=1, max_concurrent=2,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Execute", depends_on=[0]),
    ]
    wf_id = await eng.create_workflow("Pausable task", steps)

    # Start execution in background
    bg = asyncio.create_task(eng.execute_workflow(wf_id))

    # Wait for step 0 to begin executing
    await asyncio.wait_for(step_gate.wait(), timeout=2.0)

    # Pause mid-execution
    await eng.pause_workflow(wf_id)

    # Let step 0 finish
    await asyncio.wait_for(bg, timeout=2.0)

    wf = await eng.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.PAUSED.value
    # Step 0 completed, step 1 still pending
    statuses = {s["ordinal"]: s["status"] for s in wf["steps"]}
    assert statuses[0] == "completed"
    assert statuses[1] == "pending"


async def test_pause_invalid_state(engine: WorkflowEngine) -> None:
    """Pausing a completed workflow raises ValueError."""
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await engine.create_workflow("Task", steps)
    await engine.execute_workflow(wf_id)

    with pytest.raises(ValueError, match="Cannot pause"):
        await engine.pause_workflow(wf_id)


# --- Resume ---


async def test_resume_paused_workflow(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """Pause then resume — workflow eventually completes."""
    step_gate = asyncio.Event()
    call_count = 0

    async def slow_executor(role_id, instructions, context=None, messages=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            step_gate.set()
            await asyncio.sleep(0.05)
        return _make_result()

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=slow_executor)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        max_retries=1, max_concurrent=2,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Execute", depends_on=[0]),
    ]
    wf_id = await eng.create_workflow("Resumable task", steps)

    bg = asyncio.create_task(eng.execute_workflow(wf_id))
    await asyncio.wait_for(step_gate.wait(), timeout=2.0)
    await eng.pause_workflow(wf_id)
    await asyncio.wait_for(bg, timeout=2.0)

    assert (await eng.get_workflow(wf_id))["status"] == WorkflowStatus.PAUSED.value

    # Resume
    resume_task = await eng.resume_workflow(wf_id)
    await asyncio.wait_for(resume_task, timeout=2.0)

    wf = await eng.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.COMPLETED.value
    assert all(s["status"] == "completed" for s in wf["steps"])


async def test_resume_invalid_state(engine: WorkflowEngine) -> None:
    """Resuming an executing workflow raises ValueError."""
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await engine.create_workflow("Task", steps)

    # Set to executing manually
    await engine._update_workflow_status(wf_id, WorkflowStatus.EXECUTING)

    with pytest.raises(ValueError, match="Cannot resume"):
        await engine.resume_workflow(wf_id)


# --- Cancel ---


async def test_cancel_running_workflow(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """Cancel mid-execution — status CANCELLED, pending steps SKIPPED."""
    step_gate = asyncio.Event()

    async def slow_executor(role_id, instructions, context=None, messages=None, **kw):
        step_gate.set()
        await asyncio.sleep(0.05)
        return _make_result()

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=slow_executor)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        max_retries=1, max_concurrent=2,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Execute", depends_on=[0]),
    ]
    wf_id = await eng.create_workflow("Cancel task", steps)

    bg = asyncio.create_task(eng.execute_workflow(wf_id))
    await asyncio.wait_for(step_gate.wait(), timeout=2.0)
    await eng.cancel_workflow(wf_id)
    await asyncio.wait_for(bg, timeout=2.0)

    wf = await eng.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.CANCELLED.value
    skipped = [s for s in wf["steps"] if s["status"] == "skipped"]
    assert len(skipped) >= 1


async def test_cancel_paused_workflow(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """Pause then cancel is a valid transition."""
    step_gate = asyncio.Event()

    async def slow_executor(role_id, instructions, context=None, messages=None, **kw):
        step_gate.set()
        await asyncio.sleep(0.05)
        return _make_result()

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=slow_executor)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        max_retries=1, max_concurrent=2,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Execute", depends_on=[0]),
    ]
    wf_id = await eng.create_workflow("Cancel after pause", steps)

    bg = asyncio.create_task(eng.execute_workflow(wf_id))
    await asyncio.wait_for(step_gate.wait(), timeout=2.0)
    await eng.pause_workflow(wf_id)
    await asyncio.wait_for(bg, timeout=2.0)

    # Now cancel the paused workflow
    await eng.cancel_workflow(wf_id)

    wf = await eng.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.CANCELLED.value


async def test_cancel_invalid_state(engine: WorkflowEngine) -> None:
    """Cancelling a completed workflow raises ValueError."""
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await engine.create_workflow("Task", steps)
    await engine.execute_workflow(wf_id)

    with pytest.raises(ValueError, match="Cannot cancel"):
        await engine.cancel_workflow(wf_id)


# --- Events ---


async def test_pause_emits_event(
    db: Database, events: EventBus, mock_executor: AsyncMock, roles: RoleCatalog,
) -> None:
    """Pausing emits WORKFLOW_PAUSED event."""
    captured: list[Event] = []
    async def _capture(e: Event) -> None:
        captured.append(e)
    events.on(WORKFLOW_PAUSED, _capture)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
    )
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await eng.create_workflow("Task", steps)
    await eng._update_workflow_status(wf_id, WorkflowStatus.EXECUTING)

    await eng.pause_workflow(wf_id)
    assert len(captured) == 1
    assert captured[0].data["workflow_id"] == wf_id


async def test_resume_emits_event(
    db: Database, events: EventBus, mock_executor: AsyncMock, roles: RoleCatalog,
) -> None:
    """Resuming emits WORKFLOW_RESUMED event."""
    captured: list[Event] = []
    async def _capture(e: Event) -> None:
        captured.append(e)
    events.on(WORKFLOW_RESUMED, _capture)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
    )
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await eng.create_workflow("Task", steps)
    await eng._update_workflow_status(wf_id, WorkflowStatus.PAUSED)

    task = await eng.resume_workflow(wf_id)
    await asyncio.wait_for(task, timeout=2.0)

    assert len(captured) == 1
    assert captured[0].data["workflow_id"] == wf_id


async def test_cancel_emits_event(
    db: Database, events: EventBus, mock_executor: AsyncMock, roles: RoleCatalog,
) -> None:
    """Cancelling emits WORKFLOW_CANCELLED event."""
    captured: list[Event] = []
    async def _capture(e: Event) -> None:
        captured.append(e)
    events.on(WORKFLOW_CANCELLED, _capture)

    eng = WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
    )
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await eng.create_workflow("Task", steps)
    await eng._update_workflow_status(wf_id, WorkflowStatus.EXECUTING)

    await eng.cancel_workflow(wf_id)
    assert len(captured) == 1
    assert captured[0].data["workflow_id"] == wf_id


# --- Auto-resume ---


async def test_auto_resume_on_start(db: Database, events: EventBus) -> None:
    """Executing workflows inserted directly into DB get auto-resumed."""
    from openhydra.engine import Engine

    # Manually insert an executing workflow with pending steps
    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, ?, ?)",
        ("wf-orphan", WorkflowStatus.EXECUTING.value, "interrupted task"),
    )
    await db.conn.execute(
        "INSERT INTO steps (id, workflow_id, ordinal, role_id, instructions, status, depends_on) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "wf-orphan", 0, "planner", "Plan", StepStatus.PENDING.value, "[]"),
    )
    await db.conn.commit()

    eng = Engine.__new__(Engine)
    eng.db = db
    eng.workflow_engine = AsyncMock()
    eng.workflow_engine.execute_workflow = AsyncMock()
    eng._tasks = {}

    await eng._auto_resume_workflows()

    assert "wf-orphan" in eng._tasks
    eng.workflow_engine.execute_workflow.assert_called_once_with("wf-orphan")


async def test_running_steps_reset_on_auto_resume(db: Database, events: EventBus) -> None:
    """RUNNING steps are reset to PENDING during auto-resume."""
    from openhydra.engine import Engine

    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, ?, ?)",
        ("wf-stuck", WorkflowStatus.EXECUTING.value, "stuck task"),
    )
    await db.conn.execute(
        "INSERT INTO steps (id, workflow_id, ordinal, role_id, instructions, status, depends_on) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "wf-stuck", 0, "planner", "Plan", StepStatus.RUNNING.value, "[]"),
    )
    await db.conn.commit()

    eng = Engine.__new__(Engine)
    eng.db = db
    eng.workflow_engine = AsyncMock()
    eng.workflow_engine.execute_workflow = AsyncMock()
    eng._tasks = {}

    await eng._auto_resume_workflows()

    # Verify the step was reset to PENDING
    cursor = await db.conn.execute("SELECT status FROM steps WHERE id = 's1'")
    row = await cursor.fetchone()
    assert row["status"] == StepStatus.PENDING.value


async def test_paused_workflows_not_auto_resumed(db: Database, events: EventBus) -> None:
    """PAUSED workflows are left paused during auto-resume."""
    from openhydra.engine import Engine

    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, ?, ?)",
        ("wf-paused", WorkflowStatus.PAUSED.value, "paused task"),
    )
    await db.conn.commit()

    eng = Engine.__new__(Engine)
    eng.db = db
    eng.workflow_engine = AsyncMock()
    eng.workflow_engine.execute_workflow = AsyncMock()
    eng._tasks = {}

    await eng._auto_resume_workflows()

    assert "wf-paused" not in eng._tasks
    eng.workflow_engine.execute_workflow.assert_not_called()


# --- Step timeout ---


async def test_step_timeout(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """A step that exceeds max_duration_minutes is marked FAILED with STEP_TIMEOUT event."""
    timeout_events: list[Event] = []
    async def _capture_timeout(e: Event) -> None:
        timeout_events.append(e)
    events.on(STEP_TIMEOUT, _capture_timeout)

    async def slow_executor(role_id, instructions, context=None, messages=None, **kw):
        await asyncio.sleep(10)  # Will be cancelled by timeout
        return _make_result()

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=slow_executor)

    # Patch the role to have a tiny timeout
    role = roles.get("planner")
    original_budget = role.budget
    role.budget = BudgetConfig(
        max_tokens=100_000,
        max_tool_calls=200,
        max_duration_minutes=0.001,  # ~0.06 seconds
    )

    try:
        eng = WorkflowEngine(
            db=db, events=events, role_executor=mock_exec, roles=roles,
            max_retries=1, max_concurrent=2,
        )
        steps = [Step(role_id="planner", instructions="Plan slowly")]
        wf_id = await eng.create_workflow("Timeout task", steps)
        await eng.execute_workflow(wf_id)

        wf = await eng.get_workflow(wf_id)
        assert wf["status"] == WorkflowStatus.FAILED.value
        assert len(timeout_events) == 1
        assert "timed out" in timeout_events[0].data["error"]
    finally:
        role.budget = original_budget


# --- Progress events ---


async def test_progress_events(
    engine: WorkflowEngine, events: EventBus, mock_executor: AsyncMock,
) -> None:
    """Multi-step workflow emits STEP_PROGRESS events with correct counts."""
    progress_events: list[Event] = []
    async def _capture_progress(e: Event) -> None:
        progress_events.append(e)
    events.on(STEP_PROGRESS, _capture_progress)

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Execute", depends_on=[0]),
    ]
    wf_id = await engine.create_workflow("Progress task", steps)
    await engine.execute_workflow(wf_id)

    assert len(progress_events) >= 2
    # Last progress event should show 100%
    last = progress_events[-1]
    assert last.data["progress_pct"] == 100
    assert last.data["completed_steps"] == 2
    assert last.data["total_steps"] == 2
