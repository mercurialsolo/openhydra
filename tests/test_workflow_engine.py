"""Tests for WorkflowEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.gates.approval import ApprovalGate
from openhydra.gates.quality import QualityGate
from openhydra.roles.catalog import RoleCatalog
from openhydra.workflow.engine import WorkflowEngine
from openhydra.workflow.models import Step


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "roles.yaml")
    return catalog


@pytest.fixture
def events() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_executor() -> AsyncMock:
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=SessionResult(
        output={"text": "done", "quality_score": 30},
        raw_text="done",
        tokens_used=100,
        cost_usd=0.01,
    ))
    return executor


@pytest.fixture
async def engine(db: Database, events: EventBus, mock_executor: AsyncMock, roles: RoleCatalog):
    gates = {"quality": QualityGate(), "approval": ApprovalGate()}
    return WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
        gates=gates, max_retries=2, max_concurrent=2,
    )


async def test_create_workflow(engine: WorkflowEngine) -> None:
    steps = [
        Step(role_id="planner", instructions="Plan the task"),
        Step(role_id="eng.init", instructions="Set up project"),
    ]
    wf_id = await engine.create_workflow("Build an app", steps)
    assert wf_id is not None
    assert len(wf_id) == 12


async def test_execute_sequential(engine: WorkflowEngine, mock_executor: AsyncMock) -> None:
    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="eng.init", instructions="Init", depends_on=[0]),
    ]
    wf_id = await engine.create_workflow("Task", steps)
    await engine.execute_workflow(wf_id)

    wf = await engine.get_workflow(wf_id)
    assert wf["status"] == "completed"
    assert len(wf["steps"]) == 2
    assert all(s["status"] == "completed" for s in wf["steps"])
    assert mock_executor.execute.call_count == 2


async def test_execute_parallel(engine: WorkflowEngine, mock_executor: AsyncMock) -> None:
    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="eng.implement", instructions="Build A", depends_on=[0]),
        Step(role_id="eng.implement", instructions="Build B", depends_on=[0]),
        Step(role_id="test.code", instructions="Test all", depends_on=[1, 2]),
    ]
    wf_id = await engine.create_workflow("Parallel task", steps)
    await engine.execute_workflow(wf_id)

    wf = await engine.get_workflow(wf_id)
    assert wf["status"] == "completed"
    assert mock_executor.execute.call_count == 4


async def test_gate_retry(db: Database, events: EventBus, roles: RoleCatalog) -> None:
    """Test that a step is retried when quality gate fails, then passes."""
    call_count = 0

    async def varying_executor(role_id, instructions, context=None, messages=None, **kwargs):
        nonlocal call_count
        call_count += 1
        score = 20 if call_count == 1 else 30  # Fail first, pass second
        return SessionResult(
            output={"text": "result", "quality_score": score},
            raw_text="result",
            tokens_used=100,
            cost_usd=0.01,
        )

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=varying_executor)

    gates = {"quality": QualityGate()}
    engine = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        gates=gates, max_retries=3,
    )

    # Use pm.prd role which has quality gate with threshold 24
    steps = [Step(role_id="pm.prd", instructions="Write PRD")]
    wf_id = await engine.create_workflow("Test retry", steps)
    await engine.execute_workflow(wf_id)

    wf = await engine.get_workflow(wf_id)
    assert wf["status"] == "completed"
    assert call_count == 2  # Failed once, passed on retry


async def test_list_workflows(engine: WorkflowEngine) -> None:
    await engine.create_workflow("Task 1", [Step(role_id="planner", instructions="P1")])
    await engine.create_workflow("Task 2", [Step(role_id="planner", instructions="P2")])

    workflows = await engine.list_workflows()
    assert len(workflows) == 2
    inputs = {w["input"] for w in workflows}
    assert "Task 1" in inputs
    assert "Task 2" in inputs


async def test_mailbox_messages_passed_to_executor(
    db: Database, events: EventBus, roles: RoleCatalog
) -> None:
    """When mailbox has messages for a step, they're passed to execute()."""
    from openhydra.workflow.mailbox import Mailbox

    mailbox = Mailbox(db, events)
    received_messages = []

    async def capture_executor(role_id, instructions, context=None, messages=None, **kwargs):
        if messages:
            received_messages.extend(messages)
        return SessionResult(
            output={"text": "done", "quality_score": 30},
            raw_text="done", tokens_used=100, cost_usd=0.01,
        )

    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(side_effect=capture_executor)

    engine = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles,
        max_retries=1, mailbox=mailbox,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="eng.init", instructions="Init", depends_on=[0]),
    ]
    wf_id = await engine.create_workflow("Task", steps)

    # Load steps to get IDs
    loaded = await engine._load_steps(wf_id)
    step_1_id = loaded[1].id

    # Send a message to the second step
    await mailbox.send(wf_id, loaded[0].id, step_1_id, "info", "context from step 0")

    await engine.execute_workflow(wf_id)
    # The second step should have received the message
    assert len(received_messages) >= 1
    assert received_messages[0]["body"] == "context from step 0"


async def test_workflow_engine_accepts_mailbox(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """WorkflowEngine can be constructed with mailbox=None (backward compat)."""
    mock_exec = AsyncMock()
    mock_exec.execute = AsyncMock(return_value=SessionResult(
        output={"text": "ok", "quality_score": 30}, raw_text="ok", tokens_used=10, cost_usd=0.001,
    ))
    engine = WorkflowEngine(
        db=db, events=events, role_executor=mock_exec, roles=roles, mailbox=None,
    )
    steps = [Step(role_id="planner", instructions="Plan")]
    wf_id = await engine.create_workflow("Task", steps)
    await engine.execute_workflow(wf_id)
    wf = await engine.get_workflow(wf_id)
    assert wf["status"] == "completed"


async def test_cost_accumulation(engine: WorkflowEngine, mock_executor: AsyncMock) -> None:
    mock_executor.execute.return_value = SessionResult(
        output={"text": "done", "quality_score": 30},
        raw_text="done",
        tokens_used=500,
        cost_usd=0.05,
    )

    steps = [
        Step(role_id="planner", instructions="Plan"),
        Step(role_id="planner", instructions="Plan more", depends_on=[0]),
    ]
    wf_id = await engine.create_workflow("Cost test", steps)
    await engine.execute_workflow(wf_id)

    wf = await engine.get_workflow(wf_id)
    assert wf["total_cost_usd"] == pytest.approx(0.10, abs=0.001)
    assert wf["total_tokens"] == 1000
