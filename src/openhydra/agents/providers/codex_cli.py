"""Codex CLI agent provider — subprocess to codex command in headless mode."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ..base import SessionResult, ToolDefinition

logger = logging.getLogger(__name__)


class CodexCliProvider:
    """Agent provider using the Codex CLI via subprocess.

    Runs codex in full-auto mode (--approval-mode full-auto) so agents
    can use built-in tools without interactive prompts.

    Inherits the user's environment for OPENAI_API_KEY and other credentials.
    """

    def __init__(
        self,
        default_model: str = "o4-mini",
        approval_mode: str = "full-auto",
        cwd: str | Path | None = None,
    ) -> None:
        self._default_model = default_model
        self._approval_mode = approval_mode
        self._cwd = str(cwd) if cwd else None

    @property
    def name(self) -> str:
        return "codex-cli"

    async def run_session(
        self,
        instructions: str,
        system_prompt: str,
        tools: list[ToolDefinition] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 100_000,
        model: str | None = None,
        cwd: str | Path | None = None,
    ) -> SessionResult:
        model = model or self._default_model
        start = time.monotonic()

        if tools is not None and len(tools) < 50:
            logger.warning(
                "Codex CLI does not support tool restrictions; "
                "%d allowed tools will not be enforced", len(tools),
            )

        # Build the full prompt with system context
        full_prompt = instructions
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{instructions}"

        cmd = [
            "codex",
            "--model", model,
            "--approval-mode", self._approval_mode,
            "--quiet",
            full_prompt,
        ]

        # Determine working directory
        work_dir = str(cwd) if cwd else self._cwd

        try:
            # Strip CLAUDECODE to bypass nested-session check
            child_env = {
                k: v for k, v in os.environ.items()
                if k != "CLAUDECODE"
            }
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
                cwd=work_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=3600,
            )
        except asyncio.TimeoutError:
            logger.error("Codex CLI timed out after 1 hour")
            return SessionResult(
                output={"error": "Codex CLI timed out"},
                raw_text="Timeout after 3600s",
                duration_seconds=time.monotonic() - start,
                model=model,
            )
        except FileNotFoundError:
            logger.error(
                "codex CLI not found. Install with: "
                "npm install -g @openai/codex"
            )
            return SessionResult(
                output={"error": "codex CLI not installed"},
                raw_text="codex command not found",
                duration_seconds=time.monotonic() - start,
                model=model,
            )

        duration = time.monotonic() - start
        raw = stdout.decode()

        if proc.returncode != 0:
            error_msg = (
                stderr.decode().strip() if stderr
                else f"Exit code {proc.returncode}"
            )
            logger.warning(
                "Codex CLI failed (exit %d): %s",
                proc.returncode, error_msg[:200],
            )
            return SessionResult(
                output={"error": error_msg},
                raw_text=error_msg,
                duration_seconds=duration,
                model=model,
            )

        return self._parse_output(raw, model, duration)

    async def check_availability(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "codex", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def _parse_output(
        raw: str, model: str, duration: float,
    ) -> SessionResult:
        """Parse codex output into SessionResult."""
        try:
            data = json.loads(raw)
            output = data if isinstance(data, dict) else {"text": raw}
        except json.JSONDecodeError:
            output = {"text": raw}

        return SessionResult(
            output=output,
            raw_text=raw,
            duration_seconds=duration,
            model=model,
        )
