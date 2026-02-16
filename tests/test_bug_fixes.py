"""Tests for bug fixes — SQLite memory connect, Claude SDK MCP config, ToolDefinition source."""

from __future__ import annotations

from unittest.mock import AsyncMock

from openhydra.config import McpServerConfig, OpenHydraConfig, ToolsConfig
from openhydra.tools.mcp_client import McpClient


async def test_mcp_tool_definition_has_source_and_server() -> None:
    """Bug 3: ToolDefinition from MCP should have source='mcp' and mcp_server set."""
    transport = AsyncMock()
    transport.send = AsyncMock(return_value={
        "result": {
            "tools": [
                {"name": "read_file", "description": "Read a file"},
                {"name": "write_file", "description": "Write a file"},
            ]
        }
    })

    client = McpClient("my-server", transport)
    await client.connect()

    assert len(client.tools) == 2
    for tool in client.tools:
        assert tool.source == "mcp"
        assert tool.mcp_server == "my-server"


def test_build_mcp_config_stdio() -> None:
    """Bug 2: Engine should build MCP config dict for Claude SDK."""
    from openhydra.engine import Engine

    config = OpenHydraConfig(
        tools=ToolsConfig(mcp_servers=[
            McpServerConfig(
                name="test-server",
                transport="stdio",
                command="node",
                args=["server.js"],
                env={"FOO": "bar"},
            ),
        ]),
    )
    engine = Engine(config)
    mcp_config = engine._build_mcp_config()

    assert mcp_config is not None
    assert "mcpServers" in mcp_config
    server = mcp_config["mcpServers"]["test-server"]
    assert server["command"] == "node"
    assert server["args"] == ["server.js"]
    assert server["env"] == {"FOO": "bar"}


def test_build_mcp_config_empty() -> None:
    """No MCP servers -> None."""
    from openhydra.engine import Engine

    config = OpenHydraConfig()
    engine = Engine(config)
    assert engine._build_mcp_config() is None
