"""Cost control scenarios: spend caps, timeouts, circuit breakers, budget persistence.

Adapted from openhydra/tests/test_gates.py patterns.
"""

from __future__ import annotations

import time

from ..config import Scenario, ScenarioResult
from ..frameworks.base import FrameworkAdapter


async def run_cost_control(
    adapter: FrameworkAdapter,
    scenario: Scenario,
    run: int,
) -> ScenarioResult:
    """Dispatch to the correct cost control scenario."""
    handlers = {
        "cc-1": _hard_spend_cap,
        "cc-2": _step_timeout,
        "cc-3": _recursive_expansion,
        "cc-4": _budget_survives_crash,
        "cc-5": _cost_attribution,
    }
    handler = handlers.get(scenario.id)
    if not handler:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={}, score=0, notes=f"Unknown scenario {scenario.id}",
        )
    return await handler(adapter, scenario, run)


async def _hard_spend_cap(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Agent session hits budget cap; verify execution stops."""
    if not adapter.capabilities.budget_gates:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"cap_enforcement_accuracy": 0},
            score=0, notes="0 (no equivalent)",
        )

    budget = scenario.params.get("budget_usd", 1.00)

    # Create workflow with many steps, each costing $0.10
    steps = [
        {"role_id": "planner", "instructions": f"Expensive step {i}"}
        for i in range(20)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    # step_cost_usd is the harness's simulated per-step cost: 20 steps at
    # $0.10 = $2.00, so a $1.00 cap is reachable (v1's $0.01 never got there).
    wf_id = await adapter.create_workflow(
        steps, config={"budget_usd": budget, "step_cost_usd": 0.10}
    )
    status = await adapter.execute_workflow(wf_id)

    total_cost = await adapter.get_accumulated_cost(wf_id)

    # Budget should have stopped execution before all 20 steps
    completed_steps = sum(
        1 for s in status.get("steps", []) if s.get("status") == "completed"
    )
    budget_enforced = total_cost <= budget * 1.5 and completed_steps < 20

    accuracy = 100.0 if budget_enforced else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"cap_enforcement_accuracy": accuracy, "total_cost_usd": round(total_cost, 2),
                 "completed_steps": completed_steps, "budget_usd": budget},
        score=accuracy,
    )


async def _step_timeout(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Step exceeds max_duration_minutes; verify timeout fires."""
    if not adapter.capabilities.step_timeout:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"timeout_latency_ms": 99999},
            score=0, notes="0 (no equivalent)",
        )

    steps = [{"role_id": "planner", "instructions": "Slow step"}]
    wf_id = await adapter.create_workflow(
        steps, config={"max_duration_minutes": 0.001}
    )

    start = time.monotonic()
    status = await adapter.execute_workflow(wf_id)
    elapsed_ms = (time.monotonic() - start) * 1000

    timed_out = status.get("status") == "failed"
    has_timeout_error = any(
        "timed out" in (s.get("error", "") or "").lower()
        for s in status.get("steps", [])
    )

    if timed_out and has_timeout_error:
        score = 100.0
    elif timed_out:
        score = 70.0
    else:
        score = 0.0

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"timeout_latency_ms": round(elapsed_ms, 2)},
        score=score,
    )


async def _recursive_expansion(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Agent enters recursive loop; circuit breaker fires."""
    if not adapter.capabilities.budget_gates:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"cap_enforcement_accuracy": 0},
            score=0, notes="0 (no equivalent)",
        )

    # Create workflow that simulates recursive expansion
    max_calls = scenario.params.get("max_calls_per_minute", 10)
    steps = [
        {"role_id": "planner", "instructions": f"Recursive step {i}"}
        for i in range(max_calls * 3)  # 3x the limit
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(
        steps, config={"budget_usd": 0.50, "max_steps": max_calls, "step_cost_usd": 0.10}
    )
    status = await adapter.execute_workflow(wf_id)

    completed = sum(
        1 for s in status.get("steps", []) if s.get("status") == "completed"
    )
    # Should have stopped well before 3x
    capped = completed <= max_calls * 1.5

    accuracy = 100.0 if capped else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"cap_enforcement_accuracy": accuracy, "completed_steps": completed,
                 "max_steps": max_calls},
        score=accuracy,
    )


async def _budget_survives_crash(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Agent crashes and resumes; accumulated cost persists."""
    if not adapter.capabilities.crash_recovery or not adapter.capabilities.cost_attribution:
        missing = []
        if not adapter.capabilities.crash_recovery:
            missing.append("crash_recovery")
        if not adapter.capabilities.cost_attribution:
            missing.append("cost_attribution")
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"budget_persistence": False},
            score=0, notes=f"0 (no equivalent: missing {', '.join(missing)})",
        )

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(6)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps, config={"budget_usd": 5.00})

    # Execute partially, kill mid-run (shared helper: waits for a step to
    # complete and another to be in flight, then kills)
    from .crash_recovery import _execute_and_kill
    at_kill = await _execute_and_kill(adapter, wf_id, delay=0.02)

    cost_before = await adapter.get_accumulated_cost(wf_id)

    # Resume
    await adapter.resume_workflow(wf_id)
    cost_after = await adapter.get_accumulated_cost(wf_id)

    # Cost should persist (after >= before) and increase
    persisted = cost_after >= cost_before and cost_before > 0

    score = 100.0 if persisted else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"budget_persistence": persisted, "cost_before": cost_before,
                 "cost_after": cost_after,
                 "completed_at_kill": at_kill["completed_at_kill"]},
        score=score,
    )


async def _cost_attribution(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Multi-step workflow; verify per-step cost is tracked."""
    if not adapter.capabilities.cost_attribution:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"cap_enforcement_accuracy": 0},
            score=0, notes="0 (no equivalent)",
        )

    steps = [
        {"role_id": "planner", "instructions": f"Step {i}"} for i in range(5)
    ]
    for i in range(1, len(steps)):
        steps[i]["depends_on"] = [i - 1]

    wf_id = await adapter.create_workflow(steps)
    status = await adapter.execute_workflow(wf_id)

    # Check each step has non-zero cost
    step_costs = [
        s.get("cost_usd", 0) for s in status.get("steps", [])
        if s.get("status") == "completed"
    ]
    all_attributed = len(step_costs) > 0 and all(c > 0 for c in step_costs)

    # Total should match sum
    total = await adapter.get_accumulated_cost(wf_id)
    sum_steps = sum(step_costs)
    consistent = abs(total - sum_steps) < 0.001 if step_costs else False

    accuracy = 100.0 if (all_attributed and consistent) else (50.0 if all_attributed else 0.0)
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"cap_enforcement_accuracy": accuracy},
        score=accuracy,
    )
