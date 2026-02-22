"""Tests for Planner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.roles.catalog import RoleCatalog
from openhydra.workflow.planner import Planner, _extract_json_array


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    return catalog


@pytest.fixture
def mock_executor() -> AsyncMock:
    return AsyncMock()


async def test_plan_returns_steps(roles: RoleCatalog, mock_executor: AsyncMock) -> None:
    plan_json = json.dumps([
        {"role_id": "eng.init", "instructions": "Set up scaffold", "depends_on": []},
        {"role_id": "eng.implement", "instructions": "Build it", "depends_on": [0]},
    ])
    mock_executor.execute = AsyncMock(return_value=SessionResult(
        output={"text": plan_json},
        raw_text=plan_json,
    ))

    planner = Planner(role_executor=mock_executor, roles=roles)
    steps = await planner.plan("Build a web app")

    assert len(steps) == 2
    assert steps[0].role_id == "eng.init"
    assert steps[1].depends_on == [0]


async def test_plan_parses_code_block(roles: RoleCatalog, mock_executor: AsyncMock) -> None:
    raw = '```json\n[{"role_id": "planner", "instructions": "Plan", "depends_on": []}]\n```'
    mock_executor.execute = AsyncMock(return_value=SessionResult(
        output={"text": raw},
        raw_text=raw,
    ))

    planner = Planner(role_executor=mock_executor, roles=roles)
    steps = await planner.plan("Test")

    assert len(steps) == 1
    assert steps[0].role_id == "planner"


async def test_plan_fallback_to_single_step(roles: RoleCatalog, mock_executor: AsyncMock) -> None:
    mock_executor.execute = AsyncMock(return_value=SessionResult(
        output={"text": "just do the thing"},
        raw_text="just do the thing",
    ))

    planner = Planner(role_executor=mock_executor, roles=roles)
    steps = await planner.plan("Do something")

    assert len(steps) == 1
    assert steps[0].role_id == "eng.implement"


def test_extract_json_array_from_code_block() -> None:
    text = 'Here is the plan:\n```json\n[{"a": 1}]\n```\nDone.'
    result = _extract_json_array(text)
    assert result == [{"a": 1}]


def test_extract_json_array_raw() -> None:
    text = '[{"a": 1}, {"b": 2}]'
    result = _extract_json_array(text)
    assert result == [{"a": 1}, {"b": 2}]


def test_extract_json_array_none() -> None:
    result = _extract_json_array("just plain text")
    assert result is None
