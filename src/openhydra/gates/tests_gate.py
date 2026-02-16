"""Test pass gate — runs a shell command and gates on exit code 0."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import GateResult


class TestsGate:
    """Gate that runs a test command and passes if exit code is 0."""

    @property
    def name(self) -> str:
        return "tests_pass"

    async def check(
        self,
        step_output: dict[str, Any],
        context: dict[str, Any],
    ) -> GateResult:
        command = context.get("command", "uv run pytest")
        working_dir = context.get("working_dir")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            return GateResult(
                passed=False,
                message="Test command timed out after 5 minutes",
                details={"command": command},
            )
        except Exception as e:
            return GateResult(
                passed=False,
                message=f"Failed to run test command: {e}",
                details={"command": command},
            )

        passed = proc.returncode == 0
        output_text = stdout.decode()[-2000:]  # last 2000 chars

        return GateResult(
            passed=passed,
            message=f"Tests {'passed' if passed else 'failed'} (exit code {proc.returncode})",
            details={
                "command": command,
                "exit_code": proc.returncode,
                "output_tail": output_text,
            },
        )
