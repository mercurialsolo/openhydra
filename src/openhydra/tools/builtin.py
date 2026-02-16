"""Built-in tools for agent introspection — message passing, memory search, artifact listing."""

from __future__ import annotations

import json
from typing import Any

from ..agents.base import ToolDefinition
from ..memory.base import MemoryStore
from ..workflow.mailbox import Mailbox
from ..workflow.workspace import Workspace


def get_builtin_tool_definitions() -> list[ToolDefinition]:
    """Return ToolDefinition list for all built-in tools."""
    return [
        ToolDefinition(
            name="openhydra_send_message",
            description="Send a message to another workflow step (or broadcast to all).",
            input_schema={
                "type": "object",
                "properties": {
                    "to_step": {
                        "type": "string",
                        "description": "Target step ID, or omit to broadcast.",
                    },
                    "subject": {"type": "string", "description": "Message subject."},
                    "body": {"type": "string", "description": "Message body."},
                },
                "required": ["subject", "body"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="openhydra_search_memory",
            description="Search memory by collection or globally for relevant context.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "collection": {
                        "type": "string",
                        "description": (
                            "Collection to search (e.g. 'role:planner'). "
                            "Omit for global."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            source="builtin",
        ),
        ToolDefinition(
            name="openhydra_list_artifacts",
            description="List all workspace artifacts and their hashes.",
            input_schema={
                "type": "object",
                "properties": {},
            },
            source="builtin",
        ),
    ]


class BuiltinToolRouter:
    """Routes built-in tool calls to the correct handler.

    Constructed per-execution with workflow context (IDs, mailbox, memory, workspace).
    Note: built-in tools only work with the Anthropic API provider (tool-use loop).
    Claude SDK subprocess cannot call back into OpenHydra.
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: str,
        mailbox: Mailbox | None = None,
        memory: MemoryStore | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        self._workflow_id = workflow_id
        self._step_id = step_id
        self._mailbox = mailbox
        self._memory = memory
        self._workspace = workspace
        self._tool_names = {
            "openhydra_send_message",
            "openhydra_search_memory",
            "openhydra_list_artifacts",
        }

    def has_tool(self, name: str) -> bool:
        return name in self._tool_names

    def get_definitions(self) -> list[ToolDefinition]:
        return get_builtin_tool_definitions()

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "openhydra_send_message":
            return await self._send_message(args)
        elif name == "openhydra_search_memory":
            return await self._search_memory(args)
        elif name == "openhydra_list_artifacts":
            return self._list_artifacts()
        raise KeyError(f"Unknown built-in tool: {name}")

    async def _send_message(self, args: dict[str, Any]) -> str:
        if not self._mailbox:
            return json.dumps({"error": "Mailbox not available"})

        to_step = args.get("to_step")
        subject = args.get("subject", "")
        body = args.get("body", "")

        msg_id = await self._mailbox.send(
            workflow_id=self._workflow_id,
            from_step=self._step_id,
            to_step=to_step,
            subject=subject,
            body=body,
        )
        return json.dumps({"message_id": msg_id, "status": "sent"})

    async def _search_memory(self, args: dict[str, Any]) -> str:
        if not self._memory:
            return json.dumps({"error": "Memory not available"})

        query = args.get("query", "")
        collection = args.get("collection")
        limit = args.get("limit", 5)

        if collection:
            entries = await self._memory.search(collection, query, limit=limit)
        else:
            # Global search across all collections
            collections = await self._memory.list_collections()
            entries = []
            for coll in collections:
                results = await self._memory.search(coll, query, limit=2)
                entries.extend(results)
            entries.sort(key=lambda e: e.score, reverse=True)
            entries = entries[:limit]

        return json.dumps([
            {"content": e.content, "score": e.score, "metadata": e.metadata}
            for e in entries
        ])

    def _list_artifacts(self) -> str:
        if not self._workspace:
            return json.dumps({"error": "Workspace not available"})

        artifacts = self._workspace.list_artifacts()
        return json.dumps({"artifacts": artifacts})
