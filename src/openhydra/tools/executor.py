"""Tool executor — dispatches tool calls to built-in tools or MCP servers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..agents.base import ToolDefinition
from .mcp_client import McpClient

if TYPE_CHECKING:
    from .builtin import BuiltinToolRouter
    from .filesystem import FilesystemToolRouter


class ToolExecutor:
    """Routes tool calls to built-in tools first, then filesystem, then MCP.

    Aggregates tools from all registered MCP clients and dispatches
    calls to the owning server.
    """

    def __init__(self) -> None:
        self._clients: dict[str, McpClient] = {}
        self._builtin_router: BuiltinToolRouter | None = None
        self._filesystem_router: FilesystemToolRouter | None = None

    def register_mcp_client(self, server_name: str, client: McpClient) -> None:
        self._clients[server_name] = client

    def set_filesystem_router(self, router: FilesystemToolRouter) -> None:
        """Set the filesystem tool router (always-on for Anthropic API fallback)."""
        self._filesystem_router = router

    def set_builtin_router(self, router: BuiltinToolRouter) -> None:
        """Set the built-in tool router for the current execution context."""
        self._builtin_router = router

    def clear_builtin_router(self) -> None:
        """Clear the built-in tool router after execution."""
        self._builtin_router = None

    def list_all_tools(self) -> list[ToolDefinition]:
        """Aggregate tools from built-in + filesystem + all MCP clients."""
        tools: list[ToolDefinition] = []

        # Built-in OpenHydra tools first (send_message, search_memory, etc.)
        if self._builtin_router:
            tools.extend(self._builtin_router.get_definitions())

        # Filesystem tools (Read, Write, Edit, Bash, Glob, Grep)
        if self._filesystem_router:
            tools.extend(self._filesystem_router.get_definitions())

        # MCP tools (namespace if there's a conflict with existing names)
        existing_names = {t.name for t in tools}
        for server_name, client in self._clients.items():
            for tool in client.tools:
                if tool.name in existing_names:
                    namespaced = ToolDefinition(
                        name=f"{server_name}__{tool.name}",
                        description=tool.description,
                        input_schema=tool.input_schema,
                        source=tool.source,
                        mcp_server=tool.mcp_server,
                    )
                    tools.append(namespaced)
                else:
                    tools.append(tool)

        return tools

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Check built-in tools first, then filesystem, then MCP clients."""
        # Built-in OpenHydra tools take priority
        if self._builtin_router and self._builtin_router.has_tool(tool_name):
            return await self._builtin_router.execute(tool_name, arguments)

        # Filesystem tools (Read, Write, Edit, Bash, Glob, Grep)
        if self._filesystem_router and self._filesystem_router.has_tool(tool_name):
            return await self._filesystem_router.execute(tool_name, arguments)

        # MCP tools
        for client in self._clients.values():
            if client.has_tool(tool_name):
                return await client.call_tool(tool_name, arguments)

        # Check namespaced MCP tools (server__toolname format)
        if "__" in tool_name:
            server_name, real_name = tool_name.split("__", 1)
            client = self._clients.get(server_name)
            if client and client.has_tool(real_name):
                return await client.call_tool(real_name, arguments)

        raise KeyError(f"Tool '{tool_name}' not found in any source")
