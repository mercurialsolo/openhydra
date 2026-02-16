"""MCP client — connects to a single MCP server, discovers tools, proxies calls."""

from __future__ import annotations

import json
from typing import Any

from ..agents.base import ToolDefinition
from .transport import Transport


class McpClient:
    """Client for a single MCP server.

    Discovers available tools via tools/list and proxies
    tool calls via tools/call.
    """

    def __init__(self, server_name: str, transport: Transport) -> None:
        self.server_name = server_name
        self._transport = transport
        self._tools: list[ToolDefinition] = []

    async def connect(self) -> None:
        """Start transport and discover available tools."""
        await self._transport.start()
        await self._discover_tools()

    async def close(self) -> None:
        await self._transport.close()

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this MCP server and return the result."""
        response = await self._transport.send({
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if "error" in response:
            raise RuntimeError(f"MCP tool error: {response['error']}")

        result = response.get("result", {})
        # MCP tools return content blocks
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", str(c)) for c in content if isinstance(c, dict)]
            return "\n".join(texts) if texts else json.dumps(result)
        return str(content)

    def has_tool(self, tool_name: str) -> bool:
        return any(t.name == tool_name for t in self._tools)

    async def _discover_tools(self) -> None:
        """Query the MCP server for available tools."""
        response = await self._transport.send({
            "method": "tools/list",
            "params": {},
        })
        tools_raw = response.get("result", {}).get("tools", [])
        self._tools = [
            ToolDefinition(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema"),
                source="mcp",
                mcp_server=self.server_name,
            )
            for t in tools_raw
        ]
