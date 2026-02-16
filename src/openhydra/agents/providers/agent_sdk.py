"""Claude Agent SDK provider — in-process Claude CLI via async generator."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

from ..base import SessionResult, ToolDefinition

logger = logging.getLogger(__name__)

_SENTINEL = object()


@contextlib.contextmanager
def _stripped_env() -> Iterator[None]:
    """Temporarily remove env vars that interfere with nested Claude sessions.

    Restores original values on exit so other providers (e.g. anthropic-api)
    are not affected.
    """
    saved: dict[str, str | object] = {}

    # Always strip CLAUDECODE to bypass nesting check
    saved["CLAUDECODE"] = os.environ.pop("CLAUDECODE", _SENTINEL)

    # When running inside Claude Code with OAuth, strip API key so
    # the SDK's child process uses OAuth instead of a stale key.
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        saved["ANTHROPIC_API_KEY"] = os.environ.pop("ANTHROPIC_API_KEY", _SENTINEL)

    try:
        yield
    finally:
        for key, val in saved.items():
            if val is not _SENTINEL:
                os.environ[key] = val  # type: ignore[assignment]


class AgentSdkProvider:
    """Agent provider using the claude-agent-sdk Python package.

    Wraps the Claude CLI as an in-process library with streaming via
    an async generator.  Supports session persistence, in-process MCP
    tools, and proper error types.
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
        return "agent-sdk"

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

        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )
        except ImportError:
            return SessionResult(
                output={"error": "claude-agent-sdk not installed"},
                raw_text="claude-agent-sdk package not found",
                duration_seconds=time.monotonic() - start,
                model=model,
            )

        # Build options
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=self._max_turns,
            permission_mode="bypassPermissions",
        )

        if tools is not None:
            options.allowed_tools = [t.name for t in tools]

        mcp_servers = self._build_mcp_servers()
        if mcp_servers:
            options.mcp_servers = mcp_servers

        work_dir = str(cwd) if cwd else self._cwd
        if work_dir:
            options.cwd = work_dir

        # Iterate the async generator, collecting text and result
        collected_text: list[str] = []
        cost_usd = 0.0
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_create = 0

        try:
            with _stripped_env():
                async for message in query(prompt=instructions, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in getattr(message, "content", []):
                            if isinstance(block, TextBlock):
                                collected_text.append(block.text)

                    elif isinstance(message, ResultMessage):
                        if getattr(message, "is_error", False):
                            error_text = getattr(message, "result", "Unknown error")
                            return SessionResult(
                                output={"error": str(error_text)},
                                raw_text=str(error_text),
                                duration_seconds=time.monotonic() - start,
                                model=model,
                            )
                        # Extract usage and cost from ResultMessage
                        cost_usd = getattr(message, "total_cost_usd", 0.0) or 0.0
                        usage = getattr(message, "usage", None)
                        if usage:
                            # usage may be a dict or an object with attributes
                            _get = (
                                usage.get if isinstance(usage, dict)
                                else lambda k, d=0: getattr(usage, k, d)
                            )
                            input_tokens = _get("input_tokens", 0) or 0
                            output_tokens = _get("output_tokens", 0) or 0
                            cache_read = _get("cache_read_input_tokens", 0) or 0
                            cache_create = _get("cache_creation_input_tokens", 0) or 0

                        # ResultMessage may also carry final text
                        result_text = getattr(message, "result", None)
                        if result_text and isinstance(result_text, str):
                            collected_text.append(result_text)

        except Exception as e:
            logger.error("Agent SDK query failed: %s", e)
            return SessionResult(
                output={"error": str(e)},
                raw_text=str(e),
                duration_seconds=time.monotonic() - start,
                model=model,
            )

        raw_text = "\n".join(collected_text) if collected_text else ""
        total_tokens = input_tokens + output_tokens + cache_read + cache_create
        output = self._try_parse_json(raw_text)

        return SessionResult(
            output=output,
            raw_text=raw_text,
            tokens_used=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_seconds=time.monotonic() - start,
            model=model,
        )

    async def check_availability(self) -> bool:
        try:
            import claude_agent_sdk  # noqa: F401
            return True
        except ImportError:
            return False

    def _build_mcp_servers(self) -> dict[str, Any] | None:
        """Unwrap {"mcpServers": {...}} → {...} for the SDK."""
        if not self._mcp_config:
            return None
        if "mcpServers" in self._mcp_config:
            return self._mcp_config["mcpServers"]
        return self._mcp_config

    @staticmethod
    def _try_parse_json(raw_text: str) -> dict[str, Any]:
        """Try to extract structured JSON from raw text."""
        try:
            if "```json" in raw_text:
                start = raw_text.index("```json") + 7
                end = raw_text.index("```", start)
                parsed = json.loads(raw_text[start:end].strip())
                if isinstance(parsed, dict):
                    return parsed
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return {"text": raw_text}
