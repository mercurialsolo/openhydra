"""Adapter resolution for HydraBench: built-in names and bring-your-own module:Class specs."""
from __future__ import annotations

import pytest

from bench.hydrabench.frameworks.base import FrameworkAdapter, FrameworkCapabilities
from bench.hydrabench.frameworks.registry import BUILTIN, resolve_adapter


class _Mine(FrameworkAdapter):
    name = "Mine"
    capabilities = FrameworkCapabilities()

    async def setup(self): ...
    async def teardown(self): ...
    async def create_workflow(self, steps, config=None): return "wf"
    async def execute_workflow(self, workflow_id): return {"status": "completed", "steps": [], "cost_usd": 0.0}
    async def kill_workflow(self, workflow_id): ...
    async def resume_workflow(self, workflow_id): return {"status": "completed"}
    async def get_workflow_status(self, workflow_id): return {"status": "completed"}
    async def execute_tool(self, tool_name, args): return ""
    async def send_message(self, workflow_id, from_step, to_step, body): return None
    async def receive_messages(self, workflow_id, step_id): return []
    async def register_artifact(self, workflow_id, name, content): return None
    async def read_artifact(self, workflow_id, name): return None
    async def submit_via_channel(self, channel_name, task, permissions): return {}
    async def get_accumulated_cost(self, workflow_id): return 0.0


class _NotAnAdapter:
    pass


def test_builtin_names_resolve_to_their_adapters():
    assert set(BUILTIN) == {"openhydra", "langgraph", "crewai", "bare"}
    assert resolve_adapter("openhydra").name == "OpenHydra"


def test_module_colon_class_resolves_a_user_adapter():
    adapter = resolve_adapter(f"{__name__}:_Mine")
    assert isinstance(adapter, FrameworkAdapter)
    assert adapter.name == "Mine"


def test_a_class_that_is_not_an_adapter_is_refused():
    with pytest.raises(TypeError, match="FrameworkAdapter"):
        resolve_adapter(f"{__name__}:_NotAnAdapter")


def test_an_unknown_name_names_the_accepted_forms():
    with pytest.raises(ValueError, match="module:Class"):
        resolve_adapter("mine")
