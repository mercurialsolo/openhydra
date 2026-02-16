"""Tests for CodexCliProvider — all tests mock subprocess."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.agents.providers.codex_cli import CodexCliProvider


@pytest.fixture
def provider() -> CodexCliProvider:
    return CodexCliProvider()


async def test_name(provider: CodexCliProvider) -> None:
    assert provider.name == "codex-cli"


async def test_successful_session(provider: CodexCliProvider) -> None:
    output = json.dumps({"text": "Function created successfully"})

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(output.encode(), b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Create a function",
            system_prompt="You are helpful",
        )

    assert result.output == {"text": "Function created successfully"}


async def test_failed_session(provider: CodexCliProvider) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"Error occurred"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Fail",
            system_prompt="System",
        )

    assert "error" in result.output


async def test_plain_text_output(provider: CodexCliProvider) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"just plain text", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.run_session(
            instructions="Do something",
            system_prompt="System",
        )

    assert result.output == {"text": "just plain text"}


async def test_check_availability_present() -> None:
    provider = CodexCliProvider()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"0.1.0", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await provider.check_availability() is True


async def test_check_availability_missing() -> None:
    provider = CodexCliProvider()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        assert await provider.check_availability() is False
