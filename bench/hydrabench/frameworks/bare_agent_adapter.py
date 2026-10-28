"""Bare agent adapter: raw LLM + tool loop with no framework.

Represents the baseline of running an agent with:
- Direct API calls
- In-memory state
- No crash recovery
- No security primitives
- No cost control

This is the "before OpenHydra" baseline.
"""

from __future__ import annotations

import hashlib
import random
import tempfile
from pathlib import Path
from typing import Any

from .base import FrameworkAdapter, FrameworkCapabilities


class BareAgentAdapter(FrameworkAdapter):
    """Simulated bare agent (LLM + tools, no framework)."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._workflows: dict[str, dict[str, Any]] = {}
        self._tmp_dir: Path | None = None

    @property
    def name(self) -> str:
        return "Bare Agent"

    @property
    def capabilities(self) -> FrameworkCapabilities:
        return FrameworkCapabilities(
            crash_recovery=False,
            secret_stripping=False,
            durable_mailbox=False,
            durable_workspace=False,
            channel_permissions=False,
            rate_limiting=False,
            budget_gates=False,
            step_timeout=False,
            cost_attribution=False,
        )

    async def setup(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="hydrabench-bare-"))

    async def teardown(self) -> None:
        if self._tmp_dir and self._tmp_dir.exists():
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def create_workflow(
        self, steps: list[dict[str, Any]], config: dict[str, Any] | None = None,
    ) -> str:
        wf_id = f"bare-{self._rng.randint(1000, 9999)}"
        self._workflows[wf_id] = {
            "steps": [{**s, "status": "pending", "cost_usd": 0} for s in steps],
            "status": "created",
            "total_cost_usd": 0,
        }
        return wf_id

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        wf = self._workflows.get(workflow_id, {})
        for step in wf.get("steps", []):
            if step["status"] != "completed":
                step["status"] = "completed"
                cost = 0.01
                step["cost_usd"] = cost
                wf["total_cost_usd"] = round(wf.get("total_cost_usd", 0) + cost, 4)
        wf["status"] = "completed"
        return {"status": "completed", "steps": wf["steps"], "cost_usd": wf["total_cost_usd"]}

    async def kill_workflow(self, workflow_id: str) -> None:
        wf = self._workflows.get(workflow_id, {})
        wf["status"] = "failed"
        # All in-memory state lost
        for step in wf.get("steps", []):
            step["status"] = "failed"
            step["cost_usd"] = 0
        wf["total_cost_usd"] = 0

    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        # Full restart; no state survived
        wf = self._workflows.get(workflow_id, {})
        for step in wf.get("steps", []):
            step["status"] = "pending"
            step["cost_usd"] = 0
        wf["total_cost_usd"] = 0
        wf["status"] = "created"
        return await self.execute_workflow(workflow_id)

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        return self._workflows.get(workflow_id, {"status": "unknown"})

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "Bash" and "env" in args.get("command", ""):
            return "ANTHROPIC_API_KEY=sk-fake-leaked\nOPENAI_API_KEY=sk-fake\nPATH=/usr/bin"
        if tool_name == "Read":
            # No path restriction
            return "file contents visible"
        return "tool output"

    async def send_message(
        self, workflow_id: str, from_step: str, to_step: str, body: str,
    ) -> str | None:
        return None

    async def receive_messages(
        self, workflow_id: str, step_id: str,
    ) -> list[dict[str, str]]:
        return []

    async def register_artifact(
        self, workflow_id: str, name: str, content: bytes,
    ) -> str | None:
        return None

    async def read_artifact(
        self, workflow_id: str, name: str,
    ) -> bytes | None:
        return None

    async def submit_via_channel(
        self, channel_name: str, task: str, permissions: dict[str, Any],
    ) -> str | dict[str, Any]:
        return "wf-submitted"

    async def get_accumulated_cost(self, workflow_id: str) -> float:
        return 0
