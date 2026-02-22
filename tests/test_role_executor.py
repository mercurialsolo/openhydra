"""Tests for RoleExecutor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.agents.registry import AgentRegistry
from openhydra.memory.base import MemoryEntry
from openhydra.roles.catalog import RoleCatalog, RoleDefinition
from openhydra.roles.executor import RoleExecutor
from openhydra.skills.registry import SkillRegistry
from openhydra.skills.sources.filesystem import FilesystemSkillSource


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    return catalog


@pytest.fixture
def mock_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.name = "anthropic-api"
    provider.run_session = AsyncMock(return_value=SessionResult(
        output={"text": "Task completed"},
        raw_text="Task completed successfully",
        tokens_used=500,
        input_tokens=200,
        output_tokens=300,
        cost_usd=0.01,
    ))
    return provider


@pytest.fixture
def agents(mock_provider: AsyncMock) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(mock_provider, default=True)
    return registry


@pytest.fixture
def skills() -> SkillRegistry:
    registry = SkillRegistry()
    registry.add_source(FilesystemSkillSource(Path(__file__).parent.parent / "skills"))
    return registry


@pytest.fixture
def executor(roles, agents, skills) -> RoleExecutor:
    return RoleExecutor(roles=roles, agents=agents, skills=skills)


async def test_execute_simple(executor: RoleExecutor, mock_provider: AsyncMock) -> None:
    result = await executor.execute("planner", "Build a web app")
    assert result.raw_text == "Task completed successfully"
    mock_provider.run_session.assert_called_once()

    # Verify system prompt includes role info
    call_kwargs = mock_provider.run_session.call_args[1]
    assert "Planner" in call_kwargs["system_prompt"]
    assert call_kwargs["instructions"] == "Build a web app"


async def test_skills_included_in_prompt(executor: RoleExecutor, mock_provider: AsyncMock) -> None:
    # eng.init has skill_packs: [eng_harness, coding_principles]
    await executor.execute("eng.init", "Set up the project")
    call_kwargs = mock_provider.run_session.call_args[1]
    # Skills should be in the system prompt
    assert "Skill:" in call_kwargs["system_prompt"]


async def test_context_previous_outputs(executor: RoleExecutor, mock_provider: AsyncMock) -> None:
    context = {"previous_outputs": ["Step 0 output data"]}
    await executor.execute("planner", "Continue", context=context)
    call_kwargs = mock_provider.run_session.call_args[1]
    assert "Previous Step Outputs" in call_kwargs["system_prompt"]
    assert "Step 0 output data" in call_kwargs["system_prompt"]


async def test_messages_in_prompt(executor: RoleExecutor, mock_provider: AsyncMock) -> None:
    messages = [{"from": "eng.init", "body": "Project scaffolded"}]
    await executor.execute("planner", "Review", messages=messages)
    call_kwargs = mock_provider.run_session.call_args[1]
    assert "Messages from Other Agents" in call_kwargs["system_prompt"]
    assert "Project scaffolded" in call_kwargs["system_prompt"]


async def test_objectives_and_context_reads_in_prompt(
    executor: RoleExecutor, mock_provider: AsyncMock
) -> None:
    executor._roles._roles["research"] = RoleDefinition(
        id="research",
        name="Research Agent",
        description="Investigates options.",
        objectives=["Identify tradeoffs", "Recommend path"],
        context_reads=["Architecture docs", "Previous ADRs"],
    )
    await executor.execute("research", "Plan an approach")
    call_kwargs = mock_provider.run_session.call_args[1]
    prompt = call_kwargs["system_prompt"]
    assert "Objectives" in prompt
    assert "Identify tradeoffs" in prompt
    assert "Readable Context/Data" in prompt
    assert "Architecture docs" in prompt


async def test_memory_stored_after_execution(mock_provider: AsyncMock) -> None:
    roles = RoleCatalog()
    roles.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    agents = AgentRegistry()
    agents.register(mock_provider, default=True)
    skills = SkillRegistry()

    memory = AsyncMock()
    memory.search = AsyncMock(return_value=[])
    memory.store = AsyncMock(return_value="entry-id")

    executor = RoleExecutor(roles=roles, agents=agents, skills=skills, memory=memory)
    await executor.execute("planner", "Plan something")

    memory.store.assert_called_once()
    call_kwargs = memory.store.call_args[1]
    assert call_kwargs["collection"] == "role:planner"


async def test_session_context_in_prompt(mock_provider: AsyncMock) -> None:
    roles = RoleCatalog()
    roles.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    agents = AgentRegistry()
    agents.register(mock_provider, default=True)
    skills = SkillRegistry()

    memory = AsyncMock()
    memory.search = AsyncMock(return_value=[])
    memory.list_collections = AsyncMock(return_value=[])
    memory.list_entries = AsyncMock(return_value=[
        MemoryEntry(id="m1", content="USER: hi"),
        MemoryEntry(id="m2", content="ASSISTANT: hello"),
    ])
    memory.store = AsyncMock(return_value="entry-id")

    executor = RoleExecutor(roles=roles, agents=agents, skills=skills, memory=memory)
    await executor.execute(
        "planner",
        "Follow up question",
        context={"session_key": "slack:U1"},
    )

    call_kwargs = mock_provider.run_session.call_args[1]
    assert "Session Context" in call_kwargs["system_prompt"]
    assert "USER: hi" in call_kwargs["system_prompt"]
