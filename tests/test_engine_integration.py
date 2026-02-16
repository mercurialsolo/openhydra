"""Integration tests for the Engine class."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from openhydra.config import (
    AgentsConfig,
    EngineConfig,
    MemoryConfig,
    OpenHydraConfig,
    SkillsConfig,
    SkillSourceConfig,
)
from openhydra.engine import Engine


@pytest.fixture
def integration_config(tmp_path: Path) -> OpenHydraConfig:
    return OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path),
        agents=AgentsConfig(default_provider="anthropic-api"),
        memory=MemoryConfig(backend="in-memory"),
        skills=SkillsConfig(sources=[
            SkillSourceConfig(type="filesystem", path=str(Path(__file__).parent.parent / "skills")),
        ]),
    )


@pytest.fixture
def mock_anthropic_response():
    """Mock for anthropic API calls."""
    from dataclasses import dataclass, field

    @dataclass
    class _MockUsage:
        input_tokens: int = 100
        output_tokens: int = 50

    @dataclass
    class _MockTextBlock:
        type: str = "text"
        text: str = ""

    @dataclass
    class _MockResponse:
        content: list = field(default_factory=list)
        usage: _MockUsage = field(default_factory=_MockUsage)

    plan_json = json.dumps([
        {"role_id": "planner", "instructions": "Plan it", "depends_on": []},
    ])

    response = _MockResponse(content=[_MockTextBlock(text=plan_json)])
    return response


async def test_engine_start_stop(integration_config: OpenHydraConfig) -> None:
    """Engine starts and stops without error."""
    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = AsyncMock()
        engine = Engine(config=integration_config)
        await engine.start()

        assert engine.workflow_engine is not None
        assert engine.planner is not None
        assert engine.role_executor is not None
        assert engine.agents.list_available()

        await engine.stop()


async def test_engine_submit_and_status(
    integration_config: OpenHydraConfig,
    mock_anthropic_response,
) -> None:
    """Submit a task and check status."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_anthropic_response)

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = mock_client
        engine = Engine(config=integration_config)
        await engine.start()

        try:
            workflow_id = await engine.submit("Build hello world")
            assert workflow_id is not None

            # Wait for background task
            bg_task = engine._tasks.get(workflow_id)
            if bg_task:
                await bg_task

            wf = await engine.get_status(workflow_id)
            assert wf["id"] == workflow_id
            assert wf["input"] == "Build hello world"
        finally:
            await engine.stop()


async def test_engine_list_workflows(integration_config: OpenHydraConfig) -> None:
    """List workflows returns results."""
    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = AsyncMock()
        engine = Engine(config=integration_config)
        await engine.start()

        try:
            workflows = await engine.list_workflows()
            assert isinstance(workflows, list)
        finally:
            await engine.stop()


async def test_engine_not_started() -> None:
    """Methods raise RuntimeError if engine not started."""
    engine = Engine(config=OpenHydraConfig())

    with pytest.raises(RuntimeError, match="not started"):
        await engine.submit("test")

    with pytest.raises(RuntimeError, match="not started"):
        await engine.get_status("abc")

    with pytest.raises(RuntimeError, match="not started"):
        await engine.list_workflows()
