"""Channel security scenarios: privilege escalation, rate limiting, isolation.

Adapted from openhydra/tests/test_channel_permissions.py patterns.
"""

from __future__ import annotations

from ..config import Scenario, ScenarioResult
from ..frameworks.base import FrameworkAdapter


async def run_channel_security(
    adapter: FrameworkAdapter,
    scenario: Scenario,
    run: int,
) -> ScenarioResult:
    """Dispatch to the correct channel security scenario."""
    handlers = {
        "cs-1": _privilege_escalation,
        "cs-2": _event_emission,
        "cs-3": _rate_limiting,
        "cs-4": _cross_channel_isolation,
        "cs-5": _attribute_fishing,
    }
    handler = handlers.get(scenario.id)
    if not handler:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={}, score=0, notes=f"Unknown scenario {scenario.id}",
        )
    return await handler(adapter, scenario, run)


async def _privilege_escalation(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Restricted channel attempts to access engine.db or emit events."""
    if not adapter.capabilities.channel_permissions:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"escalation_blocked": 0},
            score=0, notes="0 (no equivalent)",
        )

    blocked_count = 0
    total_attempts = 3

    # Attempt 1: access DB
    try:
        result = await adapter.submit_via_channel(
            "restricted-slack",
            "__access_db__",
            {"can_submit": True, "can_access_db": False},
        )
        if isinstance(result, dict) and result.get("error"):
            blocked_count += 1
    except PermissionError:
        blocked_count += 1

    # Attempt 2: emit events
    try:
        result = await adapter.submit_via_channel(
            "restricted-slack",
            "__emit_event__",
            {"can_submit": True, "can_emit_events": False},
        )
        if isinstance(result, dict) and result.get("error"):
            blocked_count += 1
    except PermissionError:
        blocked_count += 1

    # Attempt 3: access internal attribute
    try:
        result = await adapter.submit_via_channel(
            "restricted-slack",
            "__access_workflow_engine__",
            {"can_submit": True},
        )
        if isinstance(result, dict) and result.get("error"):
            blocked_count += 1
    except PermissionError:
        blocked_count += 1

    score = (blocked_count / total_attempts) * 100
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"escalation_blocked": blocked_count},
        score=score,
    )


async def _event_emission(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Channel without emit permission tries to emit event."""
    if not adapter.capabilities.channel_permissions:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"escalation_blocked": 0},
            score=0, notes="0 (no equivalent)",
        )

    try:
        result = await adapter.submit_via_channel(
            "readonly-channel",
            "__emit_event__",
            {"can_submit": True, "can_emit_events": False},
        )
        blocked = isinstance(result, dict) and result.get("error")
    except PermissionError:
        blocked = True

    score = 100.0 if blocked else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"escalation_blocked": 1 if blocked else 0},
        score=score,
    )


async def _rate_limiting(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Channel exceeds max_submissions_per_hour; verify enforcement."""
    if not adapter.capabilities.rate_limiting:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"rate_limit_accuracy": 0},
            score=0, notes="0 (no equivalent)",
        )

    rate_limit = scenario.params.get("rate_limit", 5)
    # One channel per run: the limiter's window is an hour, so a channel
    # reused across runs is already over its limit on the second run.
    channel = f"rate-limited-channel-{run}"
    permissions = {
        "can_submit": True,
        "max_submissions_per_hour": rate_limit,
    }

    # Submit up to the limit
    accepted = 0
    for i in range(rate_limit):
        try:
            result = await adapter.submit_via_channel(
                channel, f"task-{i}", permissions,
            )
            if not (isinstance(result, dict) and result.get("error")):
                accepted += 1
        except PermissionError:
            break

    # Try one more (should be rejected)
    over_limit_blocked = False
    try:
        result = await adapter.submit_via_channel(
            channel, "one-too-many", permissions,
        )
        over_limit_blocked = isinstance(result, dict) and result.get("error")
    except PermissionError:
        over_limit_blocked = True

    accuracy = 100.0 if (accepted == rate_limit and over_limit_blocked) else 0.0
    if accepted == rate_limit and not over_limit_blocked:
        accuracy = 50.0  # Limit works but not enforced on excess

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"rate_limit_accuracy": accuracy},
        score=accuracy,
    )


async def _cross_channel_isolation(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Two channels with different permissions; verify isolation."""
    if not adapter.capabilities.channel_permissions:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"isolation_verified": False},
            score=0, notes="0 (no equivalent)",
        )

    # Channel A: can submit, no DB
    # Channel B: can submit, has DB access
    a_db_blocked = False
    try:
        result = await adapter.submit_via_channel(
            "channel-a", "__access_db__",
            {"can_submit": True, "can_access_db": False},
        )
        a_db_blocked = isinstance(result, dict) and result.get("error")
    except PermissionError:
        a_db_blocked = True

    b_db_allowed = False
    try:
        result = await adapter.submit_via_channel(
            "channel-b", "__access_db__",
            {"can_submit": True, "can_access_db": True},
        )
        b_db_allowed = not (isinstance(result, dict) and result.get("error"))
    except PermissionError:
        b_db_allowed = False

    isolated = a_db_blocked and b_db_allowed
    score = 100.0 if isolated else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"isolation_verified": isolated},
        score=score,
    )


async def _attribute_fishing(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Channel tries to access engine internals via __getattr__."""
    if not adapter.capabilities.channel_permissions:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"escalation_blocked": 0},
            score=0, notes="0 (no equivalent)",
        )

    blocked = 0
    attempts = ["workflow_engine", "_db", "__dict__", "_events"]

    for attr in attempts:
        try:
            result = await adapter.submit_via_channel(
                "fishing-channel", f"__access_{attr}__",
                {"can_submit": True},
            )
            if isinstance(result, dict) and result.get("error"):
                blocked += 1
        except PermissionError:
            blocked += 1

    score = (blocked / len(attempts)) * 100
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"escalation_blocked": blocked},
        score=score,
    )
