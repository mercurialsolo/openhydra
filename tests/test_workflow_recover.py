"""recover_workflow: a workflow whose executing process died is re-queued and resumed.

Added 2026-10-28 after HydraBench's first run with real kills showed a killed
workflow stays EXECUTING with a RUNNING step forever, and resume_workflow
refuses it. The crash is modelled the way the benchmark models it: cancel the
execution task and discard the engine object, keeping the database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openhydra.agents.base import SessionResult
from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.roles.catalog import RoleCatalog
from openhydra.workflow.engine import WorkflowEngine
from openhydra.workflow.models import Step, StepStatus, WorkflowStatus


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    return catalog


class SlowExecutor:
    """Each step sleeps long enough for a kill to land inside it."""

    tool_executor = None
    memory = None

    def __init__(self, seconds: float = 0.05) -> None:
        self.seconds = seconds
        self.calls = 0

    async def execute(self, role_id, instructions, context=None, messages=None, **kw):
        self.calls += 1
        await asyncio.sleep(self.seconds)
        return SessionResult(
            output={"text": "done", "quality_score": 30}, raw_text="done",
            tokens_used=100, cost_usd=0.01,
        )

    async def store_retry_lesson(self, **kw):
        return None


def _engine(db: Database, roles: RoleCatalog, executor: SlowExecutor) -> WorkflowEngine:
    return WorkflowEngine(
        db=db, events=EventBus(), role_executor=executor, roles=roles,
        max_retries=2, max_concurrent=2,
    )


def _chain(n: int) -> list[Step]:
    steps = [Step(role_id="planner", instructions=f"Step {i}") for i in range(n)]
    for i in range(1, n):
        steps[i].depends_on = [i - 1]
    return steps


async def _crash_mid_step(
    db: Database, roles: RoleCatalog, n: int = 4,
) -> tuple[str, WorkflowEngine]:
    """Run a chain, kill it inside step 1, return (workflow id, dead engine)."""
    executor = SlowExecutor()
    engine = _engine(db, roles, executor)
    wf_id = await engine.create_workflow(task="t", steps=_chain(n))
    task = asyncio.create_task(engine.execute_workflow(wf_id))
    for _ in range(200):
        await asyncio.sleep(0.005)
        wf = await engine.get_workflow(wf_id)
        done = sum(1 for s in wf["steps"] if s["status"] == "completed")
        running = sum(1 for s in wf["steps"] if s["status"] == "running")
        if done >= 1 and running >= 1:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return wf_id, engine


async def test_crash_leaves_running_step_and_resume_refuses(
    db: Database, roles: RoleCatalog,
) -> None:
    """The state a crash leaves behind, and why the old path cannot take it."""
    wf_id, _dead = await _crash_mid_step(db, roles)
    fresh = _engine(db, roles, SlowExecutor())
    wf = await fresh.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.EXECUTING.value
    statuses = [s["status"] for s in wf["steps"]]
    assert statuses.count(StepStatus.COMPLETED.value) == 1
    assert statuses.count(StepStatus.RUNNING.value) == 1
    with pytest.raises(ValueError, match="must be paused"):
        await fresh.resume_workflow(wf_id)


async def test_recover_requeues_running_step_and_completes(
    db: Database, roles: RoleCatalog,
) -> None:
    wf_id, _dead = await _crash_mid_step(db, roles)
    executor = SlowExecutor()
    fresh = _engine(db, roles, executor)

    task = await fresh.recover_workflow(wf_id)
    await asyncio.wait_for(task, timeout=5)

    wf = await fresh.get_workflow(wf_id)
    assert wf["status"] == WorkflowStatus.COMPLETED.value
    assert all(s["status"] == StepStatus.COMPLETED.value for s in wf["steps"])
    # One step was completed before the crash; the other three ran here,
    # including the one that was in flight. Nothing ran twice.
    assert executor.calls == 3
    assert wf["total_cost_usd"] == pytest.approx(0.04)


async def test_recover_refuses_a_live_workflow(db: Database, roles: RoleCatalog) -> None:
    executor = SlowExecutor()
    engine = _engine(db, roles, executor)
    wf_id = await engine.create_workflow(task="t", steps=_chain(3))
    task = asyncio.create_task(engine.execute_workflow(wf_id))
    await asyncio.sleep(0.02)
    with pytest.raises(ValueError, match="executing in this process"):
        await engine.recover_workflow(wf_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_recover_refuses_a_finished_workflow(db: Database, roles: RoleCatalog) -> None:
    engine = _engine(db, roles, SlowExecutor(0))
    wf_id = await engine.create_workflow(task="t", steps=_chain(2))
    await engine.execute_workflow(wf_id)
    with pytest.raises(ValueError, match="Cannot recover"):
        await engine.recover_workflow(wf_id)
