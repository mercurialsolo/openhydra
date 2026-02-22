"""Planner — uses the planner role to decompose tasks into step sequences."""

from __future__ import annotations

import json
from typing import Any

from ..roles.catalog import RoleCatalog
from ..roles.executor import RoleExecutor
from .models import Step

PLANNER_INSTRUCTIONS_TEMPLATE = """\
Analyze the following task and create a step-by-step execution plan.

## Task
{task}

## Available Roles
{roles_description}

## Output Format
Respond with ONLY a JSON array of steps. Each step has:
- "role_id": one of the available role IDs
- "instructions": specific instructions for that role
- "depends_on": list of step indices (0-based) this step depends on (empty list for no deps)

Example:
```json
[
  {{"role_id": "eng.init", "instructions": "Set up project scaffold", "depends_on": []}},
  {{"role_id": "eng.implement", "instructions": "Implement module A", "depends_on": [0]}},
  {{"role_id": "eng.implement", "instructions": "Implement module B", "depends_on": [0]}},
  {{"role_id": "test.code", "instructions": "Test all modules", "depends_on": [1, 2]}}
]
```
"""


class Planner:
    """Uses the planner role to analyze tasks and compose step sequences."""

    def __init__(
        self,
        role_executor: RoleExecutor,
        roles: RoleCatalog,
    ) -> None:
        self._role_executor = role_executor
        self._roles = roles

    async def plan(self, task: str, context: dict[str, Any] | None = None) -> list[Step]:
        """Generate a plan for the given task."""
        roles_desc = self._format_roles()

        instructions = PLANNER_INSTRUCTIONS_TEMPLATE.format(
            task=task,
            roles_description=roles_desc,
        )

        result = await self._role_executor.execute(
            role_id="planner",
            instructions=instructions,
            context=context,
        )

        return self._parse_steps(result.output, result.raw_text)

    def _format_roles(self) -> str:
        """Format available roles for the planner's context."""
        lines = []
        for role_id in self._roles.list_roles():
            if role_id == "planner":
                continue
            role = self._roles.get(role_id)
            lines.append(f"- **{role_id}**: {role.name} — {role.description}")
        return "\n".join(lines)

    @staticmethod
    def _parse_steps(output: dict[str, Any], raw_text: str) -> list[Step]:
        """Parse structured output or raw text into Step list."""
        steps_data = None

        # Try output dict first
        if isinstance(output, list):
            steps_data = output
        elif isinstance(output, dict) and "steps" in output:
            steps_data = output["steps"]

        # Try extracting JSON from raw text
        if steps_data is None:
            steps_data = _extract_json_array(raw_text)

        if not steps_data:
            # Fallback: single step
            return [Step(role_id="eng.implement", instructions=raw_text)]

        steps = []
        for i, s in enumerate(steps_data):
            steps.append(Step(
                ordinal=i,
                role_id=s.get("role_id", "eng.implement"),
                instructions=s.get("instructions", ""),
                depends_on=s.get("depends_on", []),
            ))
        return steps


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    """Try to extract a JSON array from text, possibly in a code block."""
    # Try code block first
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass

    if "```" in text:
        try:
            start = text.index("```") + 3
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass

    # Try raw text
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    return None
