"""Anthropic API agent provider — direct API calls with tool-use loop."""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

import anthropic

from ..base import SessionResult, ToolDefinition

# Cost per million tokens (input, output) by model
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
}

ToolExecutorFn = Callable[[str, dict[str, Any]], Awaitable[str]]


class AnthropicApiProvider:
    """Agent provider using the Anthropic Python SDK directly.

    Supports tool-use loops: when the model returns tool_use blocks,
    they are executed via the injected tool_executor and results fed back.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-sonnet-4-5-20250929",
        tool_executor: ToolExecutorFn | None = None,
        max_tool_rounds: int = 50,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._tool_executor = tool_executor
        self._max_tool_rounds = max_tool_rounds

    @property
    def name(self) -> str:
        return "anthropic-api"

    async def run_session(
        self,
        instructions: str,
        system_prompt: str,
        tools: list[ToolDefinition] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 100_000,
        model: str | None = None,
    ) -> SessionResult:
        model = model or self._default_model
        start = time.monotonic()

        api_tools = self._convert_tools(tools) if tools else []
        allowed_tool_names: set[str] | None = (
            {t.name for t in tools} if tools is not None else None
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": instructions}]

        total_input_tokens = 0
        total_output_tokens = 0
        raw_texts: list[str] = []

        for _ in range(self._max_tool_rounds + 1):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": min(max_tokens, 16384),
                "system": system_prompt,
                "messages": messages,
            }
            if api_tools:
                kwargs["tools"] = api_tools

            response = await self._client.messages.create(**kwargs)

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Collect text blocks
            for block in response.content:
                if block.type == "text":
                    raw_texts.append(block.text)

            # Check for tool use
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks or not self._tool_executor:
                break

            # Execute tools and build tool results
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_block in tool_use_blocks:
                # Reject tool calls not in the allowed set
                if (
                    allowed_tool_names is not None
                    and tool_block.name not in allowed_tool_names
                ):
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": f"Error: tool '{tool_block.name}' is not allowed",
                        "is_error": True,
                    })
                    continue
                try:
                    result = await self._tool_executor(tool_block.name, tool_block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result,
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        raw_text = "\n".join(raw_texts)
        output = self._parse_output(raw_text, output_schema)
        cost = self._estimate_cost(model, total_input_tokens, total_output_tokens)

        return SessionResult(
            output=output,
            raw_text=raw_text,
            tokens_used=total_input_tokens + total_output_tokens,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_usd=cost,
            duration_seconds=time.monotonic() - start,
            model=model,
        )

    async def check_availability(self) -> bool:
        try:
            await self._client.messages.create(
                model=self._default_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert ToolDefinition list to Anthropic API tool format."""
        api_tools = []
        for tool in tools:
            api_tool: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            }
            api_tools.append(api_tool)
        return api_tools

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD based on model and token usage."""
        costs = MODEL_COSTS.get(model, (3.0, 15.0))  # default to sonnet pricing
        return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000

    @staticmethod
    def _parse_output(raw_text: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        """Try to parse structured JSON from the raw text."""
        # Always try to extract JSON — agents often return structured data
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
