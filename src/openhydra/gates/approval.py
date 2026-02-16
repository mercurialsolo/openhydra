"""Approval gate — always returns requires_approval, pausing the workflow."""

from __future__ import annotations

from typing import Any

from .base import GateResult


class ApprovalGate:
    """Gate that always fails with requires_approval=True.

    The workflow engine recognizes this as a pause signal,
    not a retry signal.
    """

    @property
    def name(self) -> str:
        return "approval"

    async def check(
        self,
        step_output: dict[str, Any],
        context: dict[str, Any],
    ) -> GateResult:
        return GateResult(
            passed=False,
            message="Human approval required before proceeding",
            details={"requires_approval": True},
        )
