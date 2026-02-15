"""Quality gate protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class GateResult:
    """Result of a gate check."""

    passed: bool
    message: str = ""
    details: dict[str, Any] | None = None


@runtime_checkable
class Gate(Protocol):
    """Protocol for quality gates between workflow steps."""

    @property
    def name(self) -> str:
        """Gate identifier."""
        ...

    async def check(
        self,
        step_output: dict[str, Any],
        context: dict[str, Any],
    ) -> GateResult:
        """Check whether a step's output passes this gate.

        Args:
            step_output: The structured output from the completed step.
            context: Additional context (role config, thresholds, etc.)

        Returns:
            GateResult indicating pass/fail with explanation.
        """
        ...
