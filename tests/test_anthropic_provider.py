"""Tests for AnthropicApiProvider — all tests mock the anthropic client."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.agents.base import ToolDefinition
from openhydra.agents.providers.anthropic_api import AnthropicApiProvider


@dataclass
class MockUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = "Hello from Claude"


@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "tool_123"
    name: str = "read_file"
    input: dict = field(default_factory=lambda: {"path": "/tmp/test.py"})


@dataclass
class MockResponse:
    content: list = field(default_factory=lambda: [MockTextBlock()])
    usage: MockUsage = field(default_factory=MockUsage)


@pytest.fixture
def mock_client():
    """Create a mock anthropic async client."""
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=MockResponse())
    return client


@pytest.fixture
def provider(mock_client) -> AnthropicApiProvider:
    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = mock_client
        p = AnthropicApiProvider(api_key="test-key")
    return p


async def test_name(provider: AnthropicApiProvider) -> None:
    assert provider.name == "anthropic-api"


async def test_simple_session(provider: AnthropicApiProvider, mock_client) -> None:
    result = await provider.run_session(
        instructions="Write hello world",
        system_prompt="You are helpful",
    )
    assert "Hello from Claude" in result.raw_text
    assert result.tokens_used == 150
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cost_usd > 0
    mock_client.messages.create.assert_called_once()


async def test_with_tools(provider: AnthropicApiProvider, mock_client) -> None:
    tools = [
        ToolDefinition(
            name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    await provider.run_session(
        instructions="Read test.py",
        system_prompt="You are helpful",
        tools=tools,
    )
    call_kwargs = mock_client.messages.create.call_args[1]
    assert "tools" in call_kwargs
    assert call_kwargs["tools"][0]["name"] == "read_file"


async def test_tool_use_loop() -> None:
    """Test that tool_use blocks are executed and results fed back."""
    client = AsyncMock()
    tool_response = MockResponse(
        content=[MockToolUseBlock(), MockTextBlock(text="Using tool...")]
    )
    final_response = MockResponse(content=[MockTextBlock(text="Done!")])
    client.messages.create = AsyncMock(
        side_effect=[tool_response, final_response]
    )

    executor = AsyncMock(return_value="file contents here")

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = client
        provider = AnthropicApiProvider(api_key="test", tool_executor=executor)

    result = await provider.run_session(
        instructions="Read the file",
        system_prompt="You are helpful",
        tools=[ToolDefinition(name="read_file", description="Read a file")],
    )
    executor.assert_called_once_with("read_file", {"path": "/tmp/test.py"})
    assert "Done!" in result.raw_text
    assert client.messages.create.call_count == 2


async def test_cost_estimation(provider: AnthropicApiProvider) -> None:
    cost = provider._estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 100_000)
    # Sonnet: $3/M input + $15/M output = 3 + 1.5 = 4.5
    assert abs(cost - 4.5) < 0.01


async def test_check_availability(provider: AnthropicApiProvider, mock_client) -> None:
    assert await provider.check_availability() is True


async def test_check_availability_fails(provider: AnthropicApiProvider, mock_client) -> None:
    mock_client.messages.create.side_effect = Exception("API down")
    assert await provider.check_availability() is False
