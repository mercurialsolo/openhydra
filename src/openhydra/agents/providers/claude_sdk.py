"""Claude SDK agent provider — subprocess to claude CLI in headless mode."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..base import SessionResult, ToolDefinition

logger = logging.getLogger(__name__)


class ClaudeSdkProvider:
    """Agent provider using the Claude CLI (claude command) via subprocess.

    Runs claude in headless mode with --print and --dangerously-skip-permissions
    so agents can use built-in tools (Read, Write, Bash, Glob, Grep, etc.)
    without interactive permission prompts.

    Inherits the user's full environment (API keys, SSH agent, PATH, etc.)
    so agents have the same access as the user.
    """

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-5-20250929",
        max_turns: int = 30,
        mcp_config: dict[str, Any] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        self._default_model = default_model
        self._max_turns = max_turns
        self._mcp_config = mcp_config
        self._cwd = str(cwd) if cwd else None

    @property
    def name(self) -> str:
        return "claude-sdk"

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

        cmd = [
            "claude",
            "--print",
            "--output-format", "json",
            "--model", model,
            "--max-turns", str(self._max_turns),
            "--system-prompt", system_prompt,
            # Headless: skip interactive permission prompts
            "--dangerously-skip-permissions",
        ]

        if tools is not None:
            allowed = [t.name for t in tools]
            cmd.extend(["--allowedTools", ",".join(allowed) if allowed else ""])

        # Write MCP config to temp file if provided
        mcp_config_path = None
        if self._mcp_config:
            mcp_config_path = self._write_mcp_config(self._mcp_config)
            cmd.extend(["--mcp-config", mcp_config_path])

        # Determine working directory
        work_dir = str(cwd) if cwd else self._cwd

        try:
            # Strip CLAUDECODE to bypass nested-session check.
            # Also strip invalid ANTHROPIC_API_KEY to let Claude CLI
            # use its own OAuth token for auth instead.
            strip_keys = {"CLAUDECODE"}
            if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
                # Inside Claude Code session — let CLI use OAuth
                strip_keys.add("ANTHROPIC_API_KEY")
            child_env = {
                k: v for k, v in os.environ.items()
                if k not in strip_keys
            }
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
                cwd=work_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=instructions.encode()),
                timeout=3600,  # 1 hour max
            )
        except asyncio.TimeoutError:
            logger.error("Claude CLI timed out after 1 hour")
            return SessionResult(
                output={"error": "Claude CLI timed out"},
                raw_text="Timeout after 3600s",
                duration_seconds=time.monotonic() - start,
                model=model,
            )
        except FileNotFoundError:
            logger.error(
                "claude CLI not found. Install with: "
                "npm install -g @anthropic-ai/claude-code"
            )
            return SessionResult(
                output={"error": "claude CLI not installed"},
                raw_text="claude command not found",
                duration_seconds=time.monotonic() - start,
                model=model,
            )
        finally:
            if mcp_config_path and os.path.exists(mcp_config_path):
                os.unlink(mcp_config_path)

        duration = time.monotonic() - start

        if proc.returncode != 0:
            error_msg = (
                stderr.decode().strip() if stderr
                else f"Exit code {proc.returncode}"
            )
            logger.warning(
                "Claude CLI failed (exit %d): %s",
                proc.returncode, error_msg[:200],
            )
            return SessionResult(
                output={"error": error_msg},
                raw_text=error_msg,
                duration_seconds=duration,
                model=model,
            )

        return self._parse_output(stdout.decode(), model, duration)

    async def check_availability(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def _write_mcp_config(config: dict[str, Any]) -> str:
        """Write MCP config to a temp file, return path."""
        fd, path = tempfile.mkstemp(
            suffix=".json", prefix="openhydra_mcp_",
        )
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
        return path

    @staticmethod
    def _parse_output(
        raw: str, model: str, duration: float,
    ) -> SessionResult:
        """Parse claude CLI JSON output into SessionResult."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return SessionResult(
                output={"text": raw},
                raw_text=raw,
                duration_seconds=duration,
                model=model,
            )

        # Handle error responses
        if data.get("is_error"):
            error_msg = data.get("result", "Unknown error")
            return SessionResult(
                output={"error": str(error_msg)},
                raw_text=str(error_msg),
                duration_seconds=duration,
                model=model,
            )

        # Claude CLI JSON: {result, total_cost_usd, usage: {input_tokens, output_tokens, ...}}
        result_text = data.get("result", raw)
        if isinstance(result_text, dict):
            output = result_text
            raw_text = json.dumps(result_text)
        else:
            output = {"text": str(result_text)}
            raw_text = str(result_text)

        # Extract token usage from nested 'usage' object
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        total_tokens = input_tokens + output_tokens + cache_read + cache_create

        return SessionResult(
            output=output,
            raw_text=raw_text,
            tokens_used=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=data.get("total_cost_usd", 0.0),
            duration_seconds=duration,
            model=model,
        )
