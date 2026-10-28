"""Crash recovery scenarios: SIGKILL, repeated crashes, resume latency, state integrity.

Adapted from openhydra/tests/test_workflow_pause_resume.py patterns.
"""

from __future__ import annotations

import asyncio
import time

from ..config import Scenario, ScenarioResult
from ..frameworks.base import FrameworkAdapter


async def run_crash_recovery(
    adapter: FrameworkAdapter,
    scenario: Scenario,
    run: int,
) -> ScenarioResult:
    """Dispatch to the correct crash recovery scenario."""
    handlers = {
        "cr-1": _sigkill_during_execution,
        "cr-2": _repeated_crashes,
        "cr-3": _resume_latency,
        "cr-4": _state_integrity,
    }
    handler = handlers.get(scenario.id)
    if not handler:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={}, score=0, notes=f"Unknown scenario {scenario.id}",
        )
    return await handler(adapter, scenario, run)


async def _sigkill_during_execution(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Kill agent mid-step; verify resume from checkpoint."""
    if not adapter.capabilities.crash_recovery:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"recovery_rate": 0, "wasted_steps": 5},
            score=0, notes="0 (no equivalent)",
        )

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(5)
    ]
    # Make steps sequential
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps)

    # Start execution then kill mid-way
    at_kill = await _execute_and_kill(adapter, wf_id, delay=0.02)

    # Resume and check
    status = await adapter.resume_workflow(wf_id)
    completed = sum(
        1 for s in status.get("steps", []) if s.get("status") == "completed"
    )
    total = len(steps)
    recovery_rate = (completed / total) * 100
    wasted = total - completed

    score = recovery_rate
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"recovery_rate": recovery_rate, "wasted_steps": wasted,
                 "completed_at_kill": at_kill["completed_at_kill"],
                 "running_at_kill": at_kill["running_at_kill"],
                 "status_after_resume": status.get("status")},
        score=score,
        notes="" if at_kill["running_at_kill"] else "kill landed with no step in flight",
    )


async def _repeated_crashes(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Kill agent 3 times during a 10-step workflow."""
    if not adapter.capabilities.crash_recovery:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"recovery_rate": 0, "wasted_steps": 10},
            score=0, notes="0 (no equivalent)",
        )

    crash_count = scenario.params.get("crash_count", 3)
    total_steps = scenario.params.get("total_steps", 10)

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(total_steps)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps)

    # Kill 1 lands in the first execution; kills 2 and 3 land inside the
    # resumes that follow, so every kill interrupts work in flight. Then one
    # last resume runs to completion (or refuses: that is the measurement).
    kills: list[dict[str, int]] = []
    for crash_idx in range(crash_count):
        done_so_far, _ = await _progress(adapter, wf_id)
        kills.append(await _execute_and_kill(
            adapter, wf_id, delay=0.02, min_completed=done_so_far + 1,
            resume=crash_idx > 0,
        ))
    status = await adapter.resume_workflow(wf_id)
    completed = sum(
        1 for s in status.get("steps", []) if s.get("status") == "completed"
    )
    recovery_rate = (completed / total_steps) * 100
    wasted = total_steps - completed

    score = recovery_rate
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"recovery_rate": recovery_rate, "wasted_steps": wasted,
                 "kills_mid_step": sum(1 for k in kills if k["running_at_kill"]),
                 "completed_at_each_kill": [k["completed_at_kill"] for k in kills],
                 "status_after_resume": status.get("status")},
        score=score,
    )


async def _resume_latency(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Measure time from crash to resumed execution."""
    if not adapter.capabilities.crash_recovery:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"resume_latency_ms": 99999},
            score=0, notes="0 (no equivalent)",
        )

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(3)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps)
    at_kill = await _execute_and_kill(adapter, wf_id, delay=0.02)

    start = time.monotonic()
    status = await adapter.resume_workflow(wf_id)
    latency_ms = (time.monotonic() - start) * 1000
    recovered = status.get("status") == "completed"

    # Score: <100ms = 100, <500ms = 80, <1000ms = 50, >1000ms = 20.
    # A resume that did not bring the workflow to completion has no latency
    # to report: the engine refused or stalled, and that scores 0.
    if not recovered:
        score = 0.0
    elif latency_ms < 100:
        score = 100.0
    elif latency_ms < 500:
        score = 80.0
    elif latency_ms < 1000:
        score = 50.0
    else:
        score = 20.0

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"resume_latency_ms": round(latency_ms, 2) if recovered else None,
                 "recovered": recovered,
                 "completed_at_kill": at_kill["completed_at_kill"],
                 "running_at_kill": at_kill["running_at_kill"],
                 "status_after_resume": status.get("status")},
        score=score,
        notes="" if recovered else f"resume left workflow '{status.get('status')}'",
    )


async def _state_integrity(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Verify step outputs and cost accumulators survive crash."""
    if not adapter.capabilities.crash_recovery:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"data_integrity": False},
            score=0, notes="0 (no equivalent)",
        )

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(4)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps)
    at_kill = await _execute_and_kill(adapter, wf_id, delay=0.02)

    # Get pre-resume cost
    cost_before = await adapter.get_accumulated_cost(wf_id)

    # Resume to completion
    status = await adapter.resume_workflow(wf_id)
    cost_after = await adapter.get_accumulated_cost(wf_id)

    # Cost should only increase (never reset to 0)
    integrity = cost_after >= cost_before and cost_after > 0
    score = 100.0 if integrity else 0.0

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"data_integrity": integrity, "cost_before": cost_before,
                 "cost_after": cost_after,
                 "completed_at_kill": at_kill["completed_at_kill"],
                 "status_after_resume": status.get("status")},
        score=score,
    )


async def _progress(adapter: FrameworkAdapter, wf_id: str) -> tuple[int, int]:
    """(completed, running) step counts as the database reports them."""
    status = await adapter.get_workflow_status(wf_id)
    steps = status.get("steps", [])
    completed = sum(1 for s in steps if s.get("status") == "completed")
    running = sum(1 for s in steps if s.get("status") == "running")
    return completed, running


async def _execute_and_kill(
    adapter: FrameworkAdapter, wf_id: str, delay: float,
    min_completed: int = 1, timeout: float = 5.0, resume: bool = False,
) -> dict[str, int]:
    """Start execution (or a resume), wait until the workflow is mid-run, then kill it.

    v1 slept ``delay`` and killed; with an instant mock the workflow had
    already finished. v1.1 waits until at least ``min_completed`` steps are
    complete AND a step is running (so the kill lands inside a step), then
    waits ``delay`` more, then kills. Returns the progress at the moment of the
    kill so the scenario can report what was interrupted.
    """
    starter = adapter.resume_workflow if resume else adapter.execute_workflow
    task = asyncio.create_task(starter(wf_id))
    deadline = time.monotonic() + timeout
    completed, running = 0, 0
    try:
        while time.monotonic() < deadline and not task.done():
            completed, running = await _progress(adapter, wf_id)
            if completed >= min_completed and running >= 1:
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(delay)
        completed, running = await _progress(adapter, wf_id)
        await adapter.kill_workflow(wf_id)
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    return {"completed_at_kill": completed, "running_at_kill": running}
