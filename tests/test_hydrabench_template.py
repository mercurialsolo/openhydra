"""The template adapter runs the whole benchmark and scores honest zeros without raising."""
from __future__ import annotations

import asyncio

from bench.hydrabench.config import SCENARIOS
from bench.hydrabench.frameworks.base import FrameworkAdapter
from bench.hydrabench.frameworks.template_adapter import TemplateAdapter
from bench.hydrabench.runner import run_framework


def test_template_declares_nothing():
    caps = TemplateAdapter().capabilities
    assert not any(vars(caps).values())


def test_template_runs_every_scenario_with_no_errors_and_all_zeros():
    results = asyncio.run(run_framework(TemplateAdapter(), runs=1))
    assert {r.scenario_id for r in results} == {s.id for s in SCENARIOS}
    assert [r for r in results if r.notes.startswith("Error:")] == []
    assert all(r.score == 0 for r in results)
    assert all(r.notes.startswith("0 (no equivalent") for r in results)


def test_secret_scenarios_gate_on_the_flag_not_on_tool_output():
    class Silent(TemplateAdapter):
        async def execute_tool(self, tool_name, args):
            return ""  # would look like a clean environment if the scenario trusted output alone

    results = asyncio.run(run_framework(Silent(), runs=1))
    secret = [r for r in results if r.scenario_id.startswith("sc-")]
    assert len(secret) == 5
    assert all(r.score == 0 and r.notes == "0 (no equivalent)" for r in secret)


def test_template_is_a_framework_adapter():
    assert isinstance(TemplateAdapter(), FrameworkAdapter)
