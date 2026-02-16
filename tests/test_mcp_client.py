"""Tests for MCP client — mock transport."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from openhydra.tools.mcp_client import McpClient


class MockTransport:
    """Mock transport for testing."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._calls: list[dict[str, Any]] = []
        self.start = AsyncMock()
        self.close = AsyncMock()

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        self._calls.append(message)
        if self._responses:
            return self._responses.pop(0)
        return {"result": {}}


@pytest.fixture
def transport_with_tools() -> MockTransport:
    """Transport that returns two tools on discovery."""
    return MockTransport([
        {
            "result": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                    {
                        "name": "write_file",
                        "description": "Write a file",
                        "inputSchema": {"type": "object"},
                    },
                ]
            }
        }
    ])


async def test_connect_discovers_tools(transport_with_tools: MockTransport) -> None:
    client = McpClient("test-server", transport_with_tools)
    await client.connect()

    assert len(client.tools) == 2
    assert client.has_tool("read_file")
    assert client.has_tool("write_file")
    assert not client.has_tool("nonexistent")
    transport_with_tools.start.assert_called_once()


async def test_call_tool() -> None:
    transport = MockTransport([
        {"result": {"tools": [{"name": "greet", "description": "Greet"}]}},
        {"result": {"content": [{"type": "text", "text": "Hello, world!"}]}},
    ])
    client = McpClient("test", transport)
    await client.connect()

    result = await client.call_tool("greet", {"name": "world"})
    assert "Hello, world!" in result


async def test_call_tool_error() -> None:
    transport = MockTransport([
        {"result": {"tools": [{"name": "fail", "description": "Fail"}]}},
        {"error": {"code": -1, "message": "Tool failed"}},
    ])
    client = McpClient("test", transport)
    await client.connect()

    with pytest.raises(RuntimeError, match="MCP tool error"):
        await client.call_tool("fail", {})


async def test_close(transport_with_tools: MockTransport) -> None:
    client = McpClient("test", transport_with_tools)
    await client.connect()
    await client.close()
    transport_with_tools.close.assert_called_once()
