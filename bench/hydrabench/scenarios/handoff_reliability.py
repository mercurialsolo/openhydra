"""Handoff reliability scenarios: message survival, artifact integrity, concurrency.

Adapted from openhydra/tests/test_mailbox.py and test_workspace.py patterns.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time

from ..config import Scenario, ScenarioResult
from ..frameworks.base import FrameworkAdapter


async def run_handoff_reliability(
    adapter: FrameworkAdapter,
    scenario: Scenario,
    run: int,
) -> ScenarioResult:
    """Dispatch to the correct handoff reliability scenario."""
    handlers = {
        "hr-1": _crash_after_send,
        "hr-2": _crash_after_artifact,
        "hr-3": _concurrent_access,
        "hr-4": _large_artifact_handoff,
    }
    handler = handlers.get(scenario.id)
    if not handler:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={}, score=0, notes=f"Unknown scenario {scenario.id}",
        )
    return await handler(adapter, scenario, run)


async def _crash_after_send(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Sender crashes after writing mailbox message; receiver still gets it."""
    if not adapter.capabilities.durable_mailbox:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"message_survival_rate": 0},
            score=0, notes="0 (no equivalent)",
        )

    steps = [
        {"role_id": "planner", "instructions": "Send message"},
        {"role_id": "planner", "instructions": "Receive message", "depends_on": [0]},
    ]
    wf_id = await adapter.create_workflow(steps)

    # Send message
    msg_id = await adapter.send_message(wf_id, "step-0", "step-1", "Test payload")

    # Simulate sender crash (kill workflow before receiver runs)
    await adapter.kill_workflow(wf_id)

    # Resume and check if message survived
    await adapter.resume_workflow(wf_id)
    messages = await adapter.receive_messages(wf_id, "step-1")

    survived = any("Test payload" in m.get("body", "") for m in messages)
    rate = 100.0 if survived else 0.0

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"message_survival_rate": rate},
        score=rate,
    )


async def _crash_after_artifact(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Writer crashes after registering artifact; downstream reads it intact."""
    if not adapter.capabilities.durable_workspace:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"artifact_integrity": False},
            score=0, notes="0 (no equivalent)",
        )

    content = b"artifact-content-" + os.urandom(16)
    expected_hash = hashlib.sha256(content).hexdigest()

    steps = [
        {"role_id": "planner", "instructions": "Write artifact"},
        {"role_id": "planner", "instructions": "Read artifact", "depends_on": [0]},
    ]
    wf_id = await adapter.create_workflow(steps)

    # Register artifact
    artifact_hash = await adapter.register_artifact(wf_id, "output.bin", content)

    # Crash
    await adapter.kill_workflow(wf_id)
    await adapter.resume_workflow(wf_id)

    # Read back
    read_content = await adapter.read_artifact(wf_id, "output.bin")
    if read_content:
        actual_hash = hashlib.sha256(read_content).hexdigest()
        integrity = actual_hash == expected_hash
    else:
        integrity = False

    score = 100.0 if integrity else 0.0
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"artifact_integrity": integrity},
        score=score,
    )


async def _concurrent_access(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Multiple agents read/write workspace concurrently; no corruption."""
    if not adapter.capabilities.durable_workspace:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"artifact_integrity": False, "message_survival_rate": 0},
            score=0, notes="0 (no equivalent)",
        )

    n_agents = scenario.params.get("concurrent_agents", 4)
    wf_id = await adapter.create_workflow(
        [{"role_id": "planner", "instructions": f"Agent {i}"} for i in range(n_agents)]
    )

    # Concurrent writes
    async def write_artifact(idx: int) -> bool:
        content = f"agent-{idx}-data".encode()
        h = await adapter.register_artifact(wf_id, f"agent-{idx}.txt", content)
        return h is not None

    results = await asyncio.gather(
        *[write_artifact(i) for i in range(n_agents)],
        return_exceptions=True,
    )
    successful_writes = sum(1 for r in results if r is True)

    # Concurrent reads
    async def read_artifact(idx: int) -> bool:
        content = await adapter.read_artifact(wf_id, f"agent-{idx}.txt")
        if content is None:
            return False
        return content == f"agent-{idx}-data".encode()

    read_results = await asyncio.gather(
        *[read_artifact(i) for i in range(n_agents)],
        return_exceptions=True,
    )
    successful_reads = sum(1 for r in read_results if r is True)

    artifact_ok = successful_writes == n_agents and successful_reads == n_agents

    # Concurrent messages
    for i in range(n_agents):
        await adapter.send_message(wf_id, f"step-{i}", f"step-{(i+1) % n_agents}", f"msg-{i}")

    msg_count = 0
    for i in range(n_agents):
        msgs = await adapter.receive_messages(wf_id, f"step-{i}")
        msg_count += len(msgs)

    msg_rate = (msg_count / n_agents) * 100

    score = (50.0 if artifact_ok else 0.0) + (msg_rate / 2)
    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={"artifact_integrity": artifact_ok, "message_survival_rate": msg_rate},
        score=min(score, 100.0),
    )


async def _large_artifact_handoff(
    adapter: FrameworkAdapter, scenario: Scenario, run: int,
) -> ScenarioResult:
    """Transfer a large artifact between agents; verify SHA-256 match."""
    if not adapter.capabilities.durable_workspace:
        return ScenarioResult(
            scenario_id=scenario.id, framework=adapter.name, run=run,
            metrics={"artifact_integrity": False, "handoff_latency_ms": 99999},
            score=0, notes="0 (no equivalent)",
        )

    size = scenario.params.get("artifact_size_bytes", 10_000_000)
    content = os.urandom(size)
    expected_hash = hashlib.sha256(content).hexdigest()

    wf_id = await adapter.create_workflow([
        {"role_id": "planner", "instructions": "Write large artifact"},
        {"role_id": "planner", "instructions": "Read large artifact", "depends_on": [0]},
    ])

    start = time.monotonic()
    await adapter.register_artifact(wf_id, "large.bin", content)
    read_back = await adapter.read_artifact(wf_id, "large.bin")
    latency_ms = (time.monotonic() - start) * 1000

    integrity = False
    if read_back:
        actual_hash = hashlib.sha256(read_back).hexdigest()
        integrity = actual_hash == expected_hash

    # Score: integrity required, latency is bonus
    if not integrity:
        score = 0.0
    elif latency_ms < 500:
        score = 100.0
    elif latency_ms < 2000:
        score = 80.0
    else:
        score = 60.0

    return ScenarioResult(
        scenario_id=scenario.id, framework=adapter.name, run=run,
        metrics={
            "artifact_integrity": integrity,
            "handoff_latency_ms": round(latency_ms, 2),
        },
        score=score,
    )
