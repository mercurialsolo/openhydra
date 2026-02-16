"""Quality score gate — checks step output quality against threshold.

Scoring strategy:
1. If step_output has an explicit 'quality_score', use it directly.
2. Otherwise, infer a score from output content:
   - Error output or empty output → 0
   - Non-trivial text output → threshold (auto-pass)
"""

from __future__ import annotations

from typing import Any

from .base import GateResult

# Minimum output length (chars) to consider meaningful
_MIN_OUTPUT_LENGTH = 50


class QualityGate:
    """Gate that checks quality_score in step output against a threshold."""

    @property
    def name(self) -> str:
        return "quality"

    async def check(
        self,
        step_output: dict[str, Any],
        context: dict[str, Any],
    ) -> GateResult:
        threshold = context.get("threshold", 24)

        # Use explicit quality_score if present
        explicit = step_output.get("quality_score")
        if isinstance(explicit, (int, float)):
            passed = explicit >= threshold
            return GateResult(
                passed=passed,
                message=f"Quality score {explicit}/{threshold}"
                + (" — passed" if passed else " — failed"),
                details={"threshold": threshold, "score": explicit},
            )

        # Infer quality from output content
        score = self._infer_score(step_output, threshold)
        passed = score >= threshold
        return GateResult(
            passed=passed,
            message=f"Quality score {score}/{threshold}"
            + (" — passed" if passed else " — failed"),
            details={"threshold": threshold, "score": score, "inferred": True},
        )

    @staticmethod
    def _infer_score(output: dict[str, Any], threshold: int) -> int:
        """Infer a quality score from output content."""
        # Error output → fail
        if "error" in output:
            error_val = output["error"]
            if error_val and str(error_val).strip():
                return 0

        # Check for meaningful text content
        text = output.get("text", "")
        if not isinstance(text, str):
            text = str(text)

        # Empty or very short output → fail
        if len(text.strip()) < _MIN_OUTPUT_LENGTH:
            return 0

        # Non-trivial output → pass (score = threshold)
        return threshold
