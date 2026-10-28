"""Starting point for benchmarking your own agent runtime.

Copy this file, rename the class, and point each method at your primitives. Then:

    PYTHONPATH=. python -m bench.hydrabench.check  mypkg.adapter:MyAdapter
    PYTHONPATH=. python -m bench.hydrabench --frameworks mypkg.adapter:MyAdapter --runs 5 \\
        --output mine.json

Every capability flag below is False, so as shipped this adapter scores 0, "no equivalent", on all
23 scenarios and never raises. Flip a flag only when the methods behind it are real: a flag you
declare but do not implement is the one way to get a score you have not earned.

Which methods each claim exercises:

- crash_recovery (cr-1..4): create_workflow, execute_workflow, kill_workflow, resume_workflow,
  get_workflow_status. The kill must land while a step is running and must destroy in-memory
  engine state; only your durable layer may survive. A kill that pauses, or that lands after the
  last step finished, scores 100 for nothing.
- secret_containment (sc-1..5): execute_tool with Bash and Read. The scenarios run ``env``,
  ``curl``, ``echo $KEY``, ``/etc/passwd`` and a traversal path through your tool layer and look
  for keys in the output.
- handoff_reliability (hr-1..4): send_message, receive_messages, register_artifact, read_artifact,
  with a kill between send and receive.
- channel_security (ch-1..5): submit_via_channel with permissions that forbid the task; a blocked
  attempt returns ``{"error": ...}`` or raises PermissionError.
- cost_control (cc-1..5): create_workflow with ``budget_usd``, ``max_steps`` and
  ``max_duration_minutes`` in ``config``; execute_workflow must stop at the cap and
  get_accumulated_cost must say what was spent.
"""

from __future__ import annotations

from typing import Any

from .base import FrameworkAdapter, FrameworkCapabilities


class TemplateAdapter(FrameworkAdapter):
    """Honest-zero adapter: every method is wired, no capability is claimed."""

    def __init__(self) -> None:
        self._workflows: dict[str, dict[str, Any]] = {}
        self._next = 0

    @property
    def name(self) -> str:
        return "Template"  # your runtime's name; submit replaces it with a codename anyway

    @property
    def capabilities(self) -> FrameworkCapabilities:
        return FrameworkCapabilities(
            crash_recovery=False,      # kill mid-step, resume from the step, not from zero
            secret_stripping=False,    # tools cannot read the process env or the key files
            durable_mailbox=False,     # a message survives the sender's death
            durable_workspace=False,   # an artifact survives the writer's death, access-controlled
            channel_permissions=False, # a channel token cannot reach what it was not granted
            rate_limiting=False,       # per channel, not per model
            budget_gates=False,        # a dollar cap and a step cap that actually stop execution
            step_timeout=False,        # a wedged step is ended, not waited on forever
            cost_attribution=False,    # cost per step, in dollars
        )

    async def setup(self) -> None:
        """Open databases, start your engine, create temp dirs."""

    async def teardown(self) -> None:
        """Close what setup opened. Called even when a scenario raised."""
        self._workflows.clear()

    async def create_workflow(
        self, steps: list[dict[str, Any]], config: dict[str, Any] | None = None,
    ) -> str:
        """Persist a multi-step workflow and return its id. ``config`` may carry caps."""
        self._next += 1
        wf_id = f"wf-{self._next}"
        self._workflows[wf_id] = {
            "steps": [{**s, "status": "pending"} for s in steps],
            "status": "created",
            "config": config or {},
            "cost_usd": 0.0,
        }
        return wf_id

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Run every step. Return ``{"status", "steps", "cost_usd"}``."""
        wf = self._workflows[workflow_id]
        for step in wf["steps"]:
            step["status"] = "completed"
        wf["status"] = "completed"
        return {"status": wf["status"], "steps": wf["steps"], "cost_usd": wf["cost_usd"]}

    async def kill_workflow(self, workflow_id: str) -> None:
        """Process death while a step is running. Drop every in-memory engine object."""
        self._workflows[workflow_id]["status"] = "failed"

    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Resume from durable state. Without it, this restarts from zero, which scores 0."""
        wf = self._workflows[workflow_id]
        for step in wf["steps"]:
            step["status"] = "pending"
        return await self.execute_workflow(workflow_id)

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        return self._workflows.get(workflow_id, {"status": "unknown"})

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Run a tool through your sandbox and return its output as text."""
        return ""

    async def send_message(
        self, workflow_id: str, from_step: str, to_step: str, body: str,
    ) -> str | None:
        """Durable inter-agent message. Return its id, or None if you have no mailbox."""
        return None

    async def receive_messages(
        self, workflow_id: str, step_id: str,
    ) -> list[dict[str, str]]:
        return []

    async def register_artifact(
        self, workflow_id: str, name: str, content: bytes,
    ) -> str | None:
        """Store an artifact in a shared workspace. Return its hash, or None."""
        return None

    async def read_artifact(self, workflow_id: str, name: str) -> bytes | None:
        return None

    async def submit_via_channel(
        self, channel_name: str, task: str, permissions: dict[str, Any],
    ) -> str | dict[str, Any]:
        """Submit through a restricted channel. Forbidden work returns ``{"error": ...}``."""
        return {"error": "channels not implemented"}

    async def get_accumulated_cost(self, workflow_id: str) -> float:
        return float(self._workflows.get(workflow_id, {}).get("cost_usd", 0.0))
