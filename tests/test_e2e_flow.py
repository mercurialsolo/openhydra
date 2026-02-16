"""End-to-end flow test — verifies the full pipeline without real API calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openhydra.config import (
    AgentsConfig,
    EngineConfig,
    MemoryConfig,
    OpenHydraConfig,
    SkillsConfig,
    SkillSourceConfig,
)
from openhydra.engine import Engine


@dataclass
class _MockUsage:
    input_tokens: int = 150
    output_tokens: int = 80


@dataclass
class _MockTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _MockResponse:
    content: list = field(default_factory=list)
    usage: _MockUsage = field(default_factory=_MockUsage)


def _make_plan_response() -> _MockResponse:
    """Planner returns a 3-step plan (avoids eng.implement which has tests_pass gate)."""
    plan = json.dumps([
        {
            "role_id": "eng.init",
            "instructions": "Set up project structure with src/ and tests/ dirs",
            "depends_on": [],
        },
        {
            "role_id": "pm.prd",
            "instructions": "Write requirements for csv_to_json() function",
            "depends_on": [0],
        },
        {
            "role_id": "test.code",
            "instructions": "Write tests for csv_to_json() function",
            "depends_on": [1],
        },
    ])
    return _MockResponse(content=[_MockTextBlock(text=plan)])


def _make_step_response(text: str) -> _MockResponse:
    """Agent returns a successful step output."""
    output = json.dumps({
        "text": text,
        "quality_score": 30,
    })
    return _MockResponse(content=[_MockTextBlock(text=output)])


async def test_full_submit_plan_execute_flow(tmp_path: Path) -> None:
    """Full flow: submit -> plan -> execute steps -> complete."""
    config = OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path),
        agents=AgentsConfig(default_provider="anthropic-api"),
        memory=MemoryConfig(backend="in-memory"),
        skills=SkillsConfig(sources=[
            SkillSourceConfig(
                type="filesystem",
                path=str(Path(__file__).parent.parent / "skills"),
            ),
        ]),
    )

    # Mock the Anthropic client to return plan then step results
    mock_client = AsyncMock()
    responses = [
        _make_plan_response(),
        _make_step_response("Project structure created"),
        _make_step_response("csv_to_json() implemented"),
        _make_step_response("Tests written and passing"),
    ]
    mock_client.messages.create = AsyncMock(side_effect=responses)

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = mock_client

        engine = Engine(config=config)
        await engine.start()

        try:
            # Submit task
            wf_id = await engine.submit("Create a CSV to JSON converter")
            assert wf_id is not None
            assert len(wf_id) == 12

            # Wait for background execution
            bg_task = engine._tasks.get(wf_id)
            assert bg_task is not None
            await bg_task

            # Check workflow completed
            status = await engine.get_status(wf_id)
            assert status["status"] == "completed"
            assert status["input"] == "Create a CSV to JSON converter"
            assert len(status["steps"]) == 3
            assert all(s["status"] == "completed" for s in status["steps"])
            assert status["total_cost_usd"] > 0
            assert status["total_tokens"] > 0

            # Verify step ordering
            steps = status["steps"]
            assert steps[0]["role_id"] == "eng.init"
            assert steps[1]["role_id"] == "pm.prd"
            assert steps[2]["role_id"] == "test.code"
            assert steps[1]["depends_on"] == [0]
            assert steps[2]["depends_on"] == [1]

            # List workflows
            workflows = await engine.list_workflows()
            assert len(workflows) == 1
            assert workflows[0]["id"] == wf_id

            # Verify API was called 4 times (1 plan + 3 steps)
            assert mock_client.messages.create.call_count == 4

        finally:
            await engine.stop()


async def test_parallel_execution_flow(tmp_path: Path) -> None:
    """Steps with no dependency on each other execute (DAG parallelism)."""
    config = OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path, max_concurrent_sessions=3),
        agents=AgentsConfig(default_provider="anthropic-api"),
        memory=MemoryConfig(backend="in-memory"),
        skills=SkillsConfig(sources=[
            SkillSourceConfig(
                type="filesystem",
                path=str(Path(__file__).parent.parent / "skills"),
            ),
        ]),
    )

    # Plan with parallel steps: init -> (A || B) -> review
    # Use roles without tests_pass gate to avoid real subprocess execution
    plan = json.dumps([
        {"role_id": "planner", "instructions": "Plan", "depends_on": []},
        {"role_id": "test.code", "instructions": "Build A", "depends_on": [0]},
        {"role_id": "pm.prd", "instructions": "Build B", "depends_on": [0]},
        {"role_id": "pm.review", "instructions": "Review all", "depends_on": [1, 2]},
    ])

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[
        _MockResponse(content=[_MockTextBlock(text=plan)]),
        _make_step_response("Planned"),
        _make_step_response("Module A done"),
        _make_step_response("Module B done"),
        _make_step_response("Review passed"),
    ])

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = mock_client

        engine = Engine(config=config)
        await engine.start()

        try:
            wf_id = await engine.submit("Build two parallel modules")
            await engine._tasks[wf_id]

            status = await engine.get_status(wf_id)
            assert status["status"] == "completed"
            assert len(status["steps"]) == 4
            assert all(s["status"] == "completed" for s in status["steps"])

            # Steps 1 and 2 both depend on 0, step 3 depends on 1 and 2
            assert status["steps"][1]["depends_on"] == [0]
            assert status["steps"][2]["depends_on"] == [0]
            assert status["steps"][3]["depends_on"] == [1, 2]

        finally:
            await engine.stop()


async def test_memory_persists_across_sessions(tmp_path: Path) -> None:
    """Memory from one role execution is searchable later."""
    config = OpenHydraConfig(
        engine=EngineConfig(state_dir=tmp_path),
        agents=AgentsConfig(default_provider="anthropic-api"),
        memory=MemoryConfig(backend="in-memory"),
        skills=SkillsConfig(sources=[
            SkillSourceConfig(
                type="filesystem",
                path=str(Path(__file__).parent.parent / "skills"),
            ),
        ]),
    )

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=[
        _MockResponse(content=[_MockTextBlock(
            text=json.dumps([
                {"role_id": "planner", "instructions": "Plan", "depends_on": []},
            ])
        )]),
        _make_step_response("Planned the CSV converter project"),
    ])

    with patch("openhydra.agents.providers.anthropic_api.anthropic") as mock_mod:
        mock_mod.AsyncAnthropic.return_value = mock_client

        engine = Engine(config=config)
        await engine.start()

        try:
            wf_id = await engine.submit("Plan a CSV converter")
            await engine._tasks[wf_id]

            # Memory should have stored the planner session
            assert engine.memory is not None
            collections = await engine.memory.list_collections()
            assert "role:planner" in collections

            results = await engine.memory.search("role:planner", "CSV converter")
            assert len(results) > 0
            assert "CSV" in results[0].content or "Plan" in results[0].content

        finally:
            await engine.stop()
