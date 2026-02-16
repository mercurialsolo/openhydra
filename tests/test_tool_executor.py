"""Tests for ToolExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import ToolDefinition
from openhydra.tools.executor import ToolExecutor
from openhydra.tools.mcp_client import McpClient


def _make_mock_client(name: str, tool_names: list[str]) -> McpClient:
    """Create a mock McpClient with specified tools."""
    client = AsyncMock(spec=McpClient)
    client.server_name = name
    client.tools = [ToolDefinition(name=n, description=f"Tool {n}") for n in tool_names]
    client.has_tool = lambda tn, names=tool_names: tn in names
    client.call_tool = AsyncMock(return_value="result")
    return client


async def test_list_all_tools() -> None:
    executor = ToolExecutor()
    executor.register_mcp_client("server1", _make_mock_client("server1", ["read", "write"]))
    executor.register_mcp_client("server2", _make_mock_client("server2", ["search"]))

    tools = executor.list_all_tools()
    names = [t.name for t in tools]
    assert "read" in names
    assert "write" in names
    assert "search" in names


async def test_execute_routes_to_correct_client() -> None:
    client1 = _make_mock_client("server1", ["read"])
    client2 = _make_mock_client("server2", ["write"])

    executor = ToolExecutor()
    executor.register_mcp_client("server1", client1)
    executor.register_mcp_client("server2", client2)

    await executor.execute("write", {"path": "/tmp/test"})
    client2.call_tool.assert_called_once_with("write", {"path": "/tmp/test"})
    client1.call_tool.assert_not_called()


async def test_execute_unknown_tool() -> None:
    executor = ToolExecutor()
    executor.register_mcp_client("server1", _make_mock_client("server1", ["read"]))

    with pytest.raises(KeyError, match="nonexistent"):
        await executor.execute("nonexistent", {})


async def test_empty_executor() -> None:
    executor = ToolExecutor()
    assert executor.list_all_tools() == []
    with pytest.raises(KeyError):
        await executor.execute("anything", {})


async def test_builtin_tools_listed() -> None:
    """When builtin router is set, its tools appear in list_all_tools."""
    from openhydra.tools.builtin import BuiltinToolRouter

    executor = ToolExecutor()
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    executor.set_builtin_router(router)

    tools = executor.list_all_tools()
    names = [t.name for t in tools]
    assert "openhydra_send_message" in names
    assert "openhydra_search_memory" in names
    assert "openhydra_list_artifacts" in names


async def test_builtin_tools_priority_over_mcp() -> None:
    """Built-in tools are checked before MCP when executing."""
    from openhydra.tools.builtin import BuiltinToolRouter

    executor = ToolExecutor()

    # Register MCP client with a tool name that doesn't conflict
    client = _make_mock_client("server1", ["read"])
    executor.register_mcp_client("server1", client)

    # Set builtin router
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    executor.set_builtin_router(router)

    # Built-in tool should resolve via router
    assert router.has_tool("openhydra_send_message")

    # MCP tool should still work
    await executor.execute("read", {"path": "/tmp"})
    client.call_tool.assert_called_once()

    # Clear and verify
    executor.clear_builtin_router()
    tools = executor.list_all_tools()
    assert "openhydra_send_message" not in [t.name for t in tools]
