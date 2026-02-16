"""Tests for RoleExecutor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.agents.registry import AgentRegistry
from openhydra.roles.catalog import RoleCatalog
from openhydra.roles.executor import RoleExecutor
from openhydra.skills.registry import SkillRegistry
from openhydra.skills.sources.filesystem import FilesystemSkillSource


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "roles.yaml")
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


async def test_memory_stored_after_execution(mock_provider: AsyncMock) -> None:
    roles = RoleCatalog()
    roles.load(Path(__file__).parent.parent / "config" / "roles.yaml")
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
