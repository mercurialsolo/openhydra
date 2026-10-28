"""Framework adapter protocol for HydraBench."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class FrameworkCapabilities:
    """Declares what a framework supports natively."""
    crash_recovery: bool = False
    secret_stripping: bool = False
    durable_mailbox: bool = False
    durable_workspace: bool = False
    channel_permissions: bool = False
    rate_limiting: bool = False
    budget_gates: bool = False
    step_timeout: bool = False
    cost_attribution: bool = False


class FrameworkAdapter(ABC):
    """Protocol for framework adapters.

    Each adapter wraps a framework's primitives so scenarios can test
    them uniformly. When a framework lacks a capability, the adapter
    returns failure results (score=0) with label "0 (no equivalent)".
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable framework name."""

    @property
    @abstractmethod
    def capabilities(self) -> FrameworkCapabilities:
        """Declare framework capabilities."""

    @abstractmethod
    async def setup(self) -> None:
        """Initialize framework resources (DB, temp dirs, etc.)."""

    @abstractmethod
    async def teardown(self) -> None:
        """Clean up resources."""

    @abstractmethod
    async def create_workflow(
        self, steps: list[dict[str, Any]], config: dict[str, Any] | None = None,
    ) -> str:
        """Create a multi-step workflow. Returns workflow ID."""

    @abstractmethod
    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Execute workflow, return status dict with 'status', 'steps', 'cost_usd'."""

    @abstractmethod
    async def kill_workflow(self, workflow_id: str) -> None:
        """Simulate SIGKILL during execution."""

    @abstractmethod
    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Resume a killed/paused workflow. Returns status dict."""

    @abstractmethod
    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """Get current workflow state."""

    @abstractmethod
    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tool (Bash, Read, Write, etc.) through the framework."""

    @abstractmethod
    async def send_message(
        self, workflow_id: str, from_step: str, to_step: str, body: str,
    ) -> str | None:
        """Send inter-agent message. Returns message ID or None if unsupported."""

    @abstractmethod
    async def receive_messages(
        self, workflow_id: str, step_id: str,
    ) -> list[dict[str, str]]:
        """Receive messages for a step."""

    @abstractmethod
    async def register_artifact(
        self, workflow_id: str, name: str, content: bytes,
    ) -> str | None:
        """Register artifact in shared workspace. Returns hash or None."""

    @abstractmethod
    async def read_artifact(
        self, workflow_id: str, name: str,
    ) -> bytes | None:
        """Read artifact from shared workspace."""

    @abstractmethod
    async def submit_via_channel(
        self, channel_name: str, task: str, permissions: dict[str, Any],
    ) -> str | dict[str, Any]:
        """Submit task through a restricted channel. Returns result or error."""

    @abstractmethod
    async def get_accumulated_cost(self, workflow_id: str) -> float:
        """Get total cost accumulated for a workflow."""
