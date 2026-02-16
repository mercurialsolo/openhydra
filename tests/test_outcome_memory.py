"""Tests for outcome-aware memory — enriched metadata, success weighting, retry lessons."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.agents.registry import AgentRegistry
from openhydra.memory.backends.in_memory import InMemoryStore
from openhydra.memory.embeddings import TfidfEmbeddingProvider
from openhydra.roles.catalog import RoleCatalog, RoleDefinition
from openhydra.roles.executor import RoleExecutor


@pytest.fixture
def provider() -> TfidfEmbeddingProvider:
    return TfidfEmbeddingProvider(max_features=64)


@pytest.fixture
def memory(provider: TfidfEmbeddingProvider) -> InMemoryStore:
    return InMemoryStore(provider)


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    # Add a minimal role
    catalog._roles["test-role"] = RoleDefinition(
        id="test-role",
        name="Test Role",
        description="A test role",
    )
    return catalog


@pytest.fixture
def mock_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.name = "mock"
    agent.run_session = AsyncMock(return_value=SessionResult(
        output={"text": "result"},
        raw_text="result text",
        tokens_used=100,
        cost_usd=0.01,
    ))
    return agent


@pytest.fixture
def executor(roles: RoleCatalog, memory: InMemoryStore, mock_agent: AsyncMock) -> RoleExecutor:
    agents = AgentRegistry()
    agents.register(mock_agent, default=True)
    from openhydra.skills.registry import SkillRegistry
    return RoleExecutor(
        roles=roles,
        agents=agents,
        skills=SkillRegistry(),
        memory=memory,
    )


async def test_store_execution_outcome_enriched_metadata(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """store_execution_outcome stores success/quality/gate metadata."""
    result = SessionResult(
        output={"text": "done"}, raw_text="done", tokens_used=50, cost_usd=0.005
    )
    await executor.store_execution_outcome(
        role_id="test-role",
        instructions="build feature X",
        result=result,
        success=True,
        quality_score=85.0,
        gate_results=[{"gate": "quality", "passed": True, "message": "ok"}],
    )

    entries = await memory.search("role:test-role", "build feature", limit=1)
    assert len(entries) == 1
    meta = entries[0].metadata
    assert meta["success"] is True
    assert meta["quality_score"] == 85.0
    assert meta["gate_results"] == [{"gate": "quality", "passed": True, "message": "ok"}]


async def test_store_execution_outcome_failure(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """Failed outcomes are stored with success=False."""
    result = SessionResult(output={"error": "bad"}, raw_text="bad", tokens_used=10, cost_usd=0.001)
    await executor.store_execution_outcome(
        role_id="test-role",
        instructions="task that failed",
        result=result,
        success=False,
        was_retry=True,
        retry_attempt=1,
    )

    entries = await memory.search("role:test-role", "task failed", limit=1)
    assert len(entries) == 1
    assert entries[0].metadata["success"] is False
    assert entries[0].metadata["was_retry"] is True
    assert entries[0].metadata["retry_attempt"] == 1


async def test_store_retry_lesson(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """Retry lessons capture what failed vs what worked."""
    failed = SessionResult(
        output={"error": "syntax"}, raw_text="syntax error",
        tokens_used=10, cost_usd=0.001,
    )
    success = SessionResult(
        output={"text": "fixed"}, raw_text="fixed code",
        tokens_used=50, cost_usd=0.005,
    )

    await executor.store_retry_lesson(
        role_id="test-role",
        instructions="fix the bug",
        failed_result=failed,
        success_result=success,
        attempt=1,
    )

    entries = await memory.search("role:test-role", "fix bug", limit=1)
    assert len(entries) == 1
    assert entries[0].metadata["type"] == "retry_lesson"
    assert "FAILED" in entries[0].content
    assert "SUCCEEDED" in entries[0].content


async def test_success_weighted_search(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """Successful entries are boosted over failures in search."""
    # Store a failure
    await memory.store(
        "role:test-role", "python debugging technique alpha",
        metadata={"success": False, "quality_score": 10},
    )
    # Store a success
    await memory.store(
        "role:test-role", "python debugging technique beta",
        metadata={"success": True, "quality_score": 90},
    )

    text = await executor._search_memory("test-role", "python debugging")
    assert "[SUCCESS]" in text


async def test_cross_role_search(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """Retry lessons from other roles are included in search."""
    # Store a retry lesson in a different role's collection
    await memory.store(
        "role:other-role", "avoid using recursive approach for large data",
        metadata={"type": "retry_lesson", "success": True},
    )

    # Search from test-role should find the cross-role lesson
    text = await executor._search_memory("test-role", "recursive approach large data")
    assert "[LESSON]" in text


async def test_backward_compat_execute_stores_memory(
    executor: RoleExecutor, memory: InMemoryStore
) -> None:
    """Default execute() with store_memory=True still stores summary."""
    await executor.execute("test-role", "do something simple")
    entries = await memory.search("role:test-role", "something simple", limit=1)
    assert len(entries) >= 1
