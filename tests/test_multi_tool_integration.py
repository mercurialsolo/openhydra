"""Integration tests — built-in tools during execution, MCP config, workspace per-workflow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import ToolDefinition
from openhydra.config import McpServerConfig, OpenHydraConfig, ToolsConfig
from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.memory.backends.in_memory import InMemoryStore
from openhydra.memory.embeddings import TfidfEmbeddingProvider
from openhydra.roles.catalog import RoleCatalog
from openhydra.tools.builtin import BuiltinToolRouter
from openhydra.tools.executor import ToolExecutor
from openhydra.workflow.mailbox import Mailbox


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    return catalog


@pytest.fixture
def events() -> EventBus:
    return EventBus()


async def test_agent_uses_send_message_tool(
    db: Database, events: EventBus, roles: RoleCatalog,
) -> None:
    """Agent can use openhydra_send_message built-in tool during execution."""
    mailbox = Mailbox(db, events)

    # Create workflow first (for FK)
    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, ?, ?)",
        ("test-wf", "executing", "test"),
    )
    await db.conn.commit()

    router = BuiltinToolRouter(
        workflow_id="test-wf", step_id="step1", mailbox=mailbox,
    )

    result = await router.execute("openhydra_send_message", {
        "to_step": "step2",
        "subject": "handoff",
        "body": "Here is the output from my analysis",
    })
    data = json.loads(result)
    assert data["status"] == "sent"

    # Verify the message was persisted
    msgs = await mailbox.receive("test-wf", "step2")
    assert len(msgs) == 1
    assert msgs[0].body == "Here is the output from my analysis"


async def test_agent_uses_search_memory_tool() -> None:
    """Agent can use openhydra_search_memory built-in tool during execution."""
    provider = TfidfEmbeddingProvider(max_features=64)
    memory = InMemoryStore(provider)

    # Pre-populate memory
    await memory.store("role:eng", "always use pytest for testing python code")
    await memory.store("role:eng", "use ruff for linting python code")

    router = BuiltinToolRouter(
        workflow_id="wf1", step_id="s1", memory=memory,
    )
    result = await router.execute("openhydra_search_memory", {
        "query": "testing python",
        "collection": "role:eng",
        "limit": 2,
    })
    entries = json.loads(result)
    assert len(entries) >= 1
    assert any("pytest" in e["content"] for e in entries)


async def test_mixed_builtin_and_mcp_tools_listed() -> None:
    """list_all_tools includes both built-in and MCP tools without conflicts."""
    executor = ToolExecutor()

    # Register an MCP client mock
    client = AsyncMock()
    client.server_name = "files"
    client.tools = [
        ToolDefinition(name="read_file", description="Read file", source="mcp", mcp_server="files"),
        ToolDefinition(
            name="write_file", description="Write file",
            source="mcp", mcp_server="files",
        ),
    ]
    client.has_tool = lambda name: name in ("read_file", "write_file")
    executor.register_mcp_client("files", client)

    # Set up builtin router
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    executor.set_builtin_router(router)

    tools = executor.list_all_tools()
    names = [t.name for t in tools]

    # All built-in tools present
    assert "openhydra_send_message" in names
    assert "openhydra_search_memory" in names
    assert "openhydra_list_artifacts" in names

    # All MCP tools present
    assert "read_file" in names
    assert "write_file" in names

    # Total count: 3 builtin + 2 MCP = 5
    assert len(tools) == 5


def test_claude_sdk_receives_mcp_config() -> None:
    """Engine builds MCP config dict that Claude SDK provider can use."""
    from openhydra.engine import Engine

    config = OpenHydraConfig(
        tools=ToolsConfig(mcp_servers=[
            McpServerConfig(
                name="filesystem",
                transport="stdio",
                command="node",
                args=["dist/index.js", "/tmp"],
            ),
            McpServerConfig(
                name="web",
                transport="sse",
                url="http://localhost:3000/sse",
            ),
        ]),
    )
    engine = Engine(config)
    # Simulate successful connection so _build_mcp_config includes them
    engine._connected_mcp_servers.update({"filesystem", "web"})
    mcp_config = engine._build_mcp_config()

    assert mcp_config is not None
    servers = mcp_config["mcpServers"]
    assert "filesystem" in servers
    assert servers["filesystem"]["command"] == "node"
    assert servers["filesystem"]["args"] == ["dist/index.js", "/tmp"]
    assert "web" in servers
    assert servers["web"]["url"] == "http://localhost:3000/sse"
    assert servers["web"]["transport"] == "sse"
