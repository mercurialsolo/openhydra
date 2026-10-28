"""LangGraph simulated adapter.

LangGraph provides state management via checkpoints but lacks:
- Native secret stripping (env isolation)
- Durable inter-agent mailbox
- Per-channel permission proxy
- Built-in rate limiting
- Budget gates / cost attribution

Scores reflect LangGraph's real capabilities based on documentation
and public benchmarks. Uses deterministic mock execution.
"""

from __future__ import annotations

import hashlib
import os
import random
import tempfile
from pathlib import Path
from typing import Any

from .base import FrameworkAdapter, FrameworkCapabilities


class LangGraphAdapter(FrameworkAdapter):
    """Simulated LangGraph adapter with realistic capability modeling."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._workflows: dict[str, dict[str, Any]] = {}
        self._artifacts: dict[str, dict[str, bytes]] = {}
        self._tmp_dir: Path | None = None

    @property
    def name(self) -> str:
        return "LangGraph"

    @property
    def capabilities(self) -> FrameworkCapabilities:
        return FrameworkCapabilities(
            crash_recovery=True,    # StateGraph checkpoints
            secret_stripping=False,  # No native env isolation
            durable_mailbox=False,   # No persistent inter-agent queue
            durable_workspace=True,  # File I/O works but no access control
            channel_permissions=False,
            rate_limiting=False,
            budget_gates=False,
            step_timeout=True,       # via asyncio timeout wrapper
            cost_attribution=False,  # No native per-step cost tracking
        )

    async def setup(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="hydrabench-lg-"))

    async def teardown(self) -> None:
        if self._tmp_dir and self._tmp_dir.exists():
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def create_workflow(
        self, steps: list[dict[str, Any]], config: dict[str, Any] | None = None,
    ) -> str:
        wf_id = f"lg-{self._rng.randint(1000, 9999)}"
        self._workflows[wf_id] = {
            "steps": [
                {**s, "status": "pending", "cost_usd": 0}
                for s in steps
            ],
            "status": "created",
            "total_cost_usd": 0,
            "config": config or {},
        }
        return wf_id

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        wf = self._workflows.get(workflow_id, {})
        steps = wf.get("steps", [])

        for step in steps:
            if step["status"] == "completed":
                continue
            step["status"] = "completed"
            cost = 0.01 + self._rng.random() * 0.005
            step["cost_usd"] = round(cost, 4)
            wf["total_cost_usd"] = round(wf.get("total_cost_usd", 0) + cost, 4)

        wf["status"] = "completed"
        return {"status": "completed", "steps": steps, "cost_usd": wf["total_cost_usd"]}

    async def kill_workflow(self, workflow_id: str) -> None:
        wf = self._workflows.get(workflow_id, {})
        wf["status"] = "paused"

    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        wf = self._workflows.get(workflow_id, {})
        # LangGraph can resume from checkpoint, but with some overhead
        wf["status"] = "executing"
        return await self.execute_workflow(workflow_id)

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        return self._workflows.get(workflow_id, {"status": "unknown"})

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        # LangGraph doesn't strip env vars natively
        if tool_name == "Bash":
            cmd = args.get("command", "")
            if "env" in cmd:
                # Simulates leaking secrets (no native stripping)
                return "ANTHROPIC_API_KEY=sk-fake-leaked\nPATH=/usr/bin"  # pragma: allowlist secret
            return "command output"
        if tool_name == "Read":
            # No path restriction by default
            return "file contents"
        return f"Tool {tool_name} executed"

    async def send_message(
        self, workflow_id: str, from_step: str, to_step: str, body: str,
    ) -> str | None:
        # No durable mailbox; returns None
        return None

    async def receive_messages(
        self, workflow_id: str, step_id: str,
    ) -> list[dict[str, str]]:
        return []

    async def register_artifact(
        self, workflow_id: str, name: str, content: bytes,
    ) -> str | None:
        self._artifacts.setdefault(workflow_id, {})[name] = content
        return hashlib.sha256(content).hexdigest()

    async def read_artifact(
        self, workflow_id: str, name: str,
    ) -> bytes | None:
        return self._artifacts.get(workflow_id, {}).get(name)

    async def submit_via_channel(
        self, channel_name: str, task: str, permissions: dict[str, Any],
    ) -> str | dict[str, Any]:
        # No channel permission model; everything passes through
        return "wf-submitted"

    async def get_accumulated_cost(self, workflow_id: str) -> float:
        # No native cost tracking
        return 0
