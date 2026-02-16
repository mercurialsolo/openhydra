"""Tests for ClaudeSdkProvider — all tests mock subprocess."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.agents.providers.claude_sdk import ClaudeSdkProvider


@pytest.fixture
def provider() -> ClaudeSdkProvider:
    return ClaudeSdkProvider()


async def test_name(provider: ClaudeSdkProvider) -> None:
    assert provider.name == "claude-sdk"


async def test_successful_session(provider: ClaudeSdkProvider) -> None:
    output = json.dumps({
        "result": "Hello world function created",
        "is_error": False,
        "total_cost_usd": 0.01,
        "usage": {
            "input_tokens": 200,
            "output_tokens": 300,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    })

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(output.encode(), b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Create hello world",
            system_prompt="You are helpful",
        )

    assert result.output == {"text": "Hello world function created"}
    assert result.tokens_used == 500
    assert result.cost_usd == 0.01


async def test_failed_session(provider: ClaudeSdkProvider) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"API key invalid"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Fail",
            system_prompt="You are helpful",
        )

    assert "error" in result.output
    assert "API key invalid" in result.raw_text


async def test_non_json_output(provider: ClaudeSdkProvider) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"plain text output", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Do something",
            system_prompt="System",
        )

    assert result.output == {"text": "plain text output"}


async def test_check_availability_present() -> None:
    provider = ClaudeSdkProvider()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"1.0.0", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await provider.check_availability() is True


async def test_check_availability_missing() -> None:
    provider = ClaudeSdkProvider()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        assert await provider.check_availability() is False


async def test_mcp_config_passed() -> None:
    mcp_config = {"mcpServers": {"chrome": {"command": "npx"}}}
    provider = ClaudeSdkProvider(mcp_config=mcp_config)

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await provider.run_session(
            instructions="Test",
            system_prompt="System",
        )

    # Verify --mcp-config was in the command
    call_args = mock_exec.call_args[0]
    assert "--mcp-config" in call_args
