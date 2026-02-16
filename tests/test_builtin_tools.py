"""Tests for built-in tools — send_message, search_memory, list_artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.memory.backends.in_memory import InMemoryStore
from openhydra.memory.embeddings import TfidfEmbeddingProvider
from openhydra.tools.builtin import BuiltinToolRouter, get_builtin_tool_definitions
from openhydra.workflow.mailbox import Mailbox
from openhydra.workflow.workspace import Workspace


def test_builtin_definitions_returned() -> None:
    """get_builtin_tool_definitions returns all three tools."""
    defs = get_builtin_tool_definitions()
    names = {d.name for d in defs}
    assert "openhydra_send_message" in names
    assert "openhydra_search_memory" in names
    assert "openhydra_list_artifacts" in names
    for d in defs:
        assert d.source == "builtin"


def test_router_has_tool() -> None:
    """Router recognizes built-in tool names."""
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    assert router.has_tool("openhydra_send_message")
    assert router.has_tool("openhydra_search_memory")
    assert router.has_tool("openhydra_list_artifacts")
    assert not router.has_tool("nonexistent_tool")


async def test_send_message(db: Database) -> None:
    """Built-in send_message dispatches to mailbox."""
    events = EventBus()
    mailbox = Mailbox(db, events)

    # Create a workflow row so foreign key is satisfied
    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, ?, ?)",
        ("w1", "executing", "test task"),
    )
    await db.conn.commit()

    router = BuiltinToolRouter(
        workflow_id="w1", step_id="s1", mailbox=mailbox,
    )
    result = await router.execute("openhydra_send_message", {
        "to_step": "s2",
        "subject": "hello",
        "body": "world",
    })
    data = json.loads(result)
    assert data["status"] == "sent"
    assert "message_id" in data


async def test_send_message_no_mailbox() -> None:
    """Without mailbox, send_message returns error."""
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    result = await router.execute("openhydra_send_message", {
        "subject": "test", "body": "body",
    })
    data = json.loads(result)
    assert "error" in data


async def test_search_memory() -> None:
    """Built-in search_memory queries the memory store."""
    provider = TfidfEmbeddingProvider(max_features=64)
    memory = InMemoryStore(provider)
    await memory.store("role:test", "python debugging guide", metadata={"type": "guide"})

    router = BuiltinToolRouter(
        workflow_id="w1", step_id="s1", memory=memory,
    )
    result = await router.execute("openhydra_search_memory", {
        "query": "python debugging",
        "collection": "role:test",
        "limit": 3,
    })
    entries = json.loads(result)
    assert len(entries) >= 1
    assert "python" in entries[0]["content"]


async def test_search_memory_global() -> None:
    """Global search (no collection) searches all collections."""
    provider = TfidfEmbeddingProvider(max_features=64)
    memory = InMemoryStore(provider)
    await memory.store("role:a", "alpha data science")
    await memory.store("role:b", "beta machine learning")

    router = BuiltinToolRouter(
        workflow_id="w1", step_id="s1", memory=memory,
    )
    result = await router.execute("openhydra_search_memory", {
        "query": "data science machine learning",
    })
    entries = json.loads(result)
    assert len(entries) >= 1


async def test_list_artifacts(tmp_path: Path) -> None:
    """Built-in list_artifacts returns workspace artifacts."""
    events = EventBus()
    ws = Workspace("w1", tmp_path, events)
    ws.register_artifact("test.txt", b"hello")

    router = BuiltinToolRouter(
        workflow_id="w1", step_id="s1", workspace=ws,
    )
    result = await router.execute("openhydra_list_artifacts", {})
    data = json.loads(result)
    assert "test.txt" in data["artifacts"]


async def test_list_artifacts_no_workspace() -> None:
    """Without workspace, list_artifacts returns error."""
    router = BuiltinToolRouter(workflow_id="w1", step_id="s1")
    result = await router.execute("openhydra_list_artifacts", {})
    data = json.loads(result)
    assert "error" in data
