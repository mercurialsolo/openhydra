"""Role catalog — loads and validates role definitions from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class GateConfig:
    type: str  # quality | tests_pass | approval
    threshold: int | None = None  # for quality gates
    command: str | None = None  # for test gates


@dataclass
class BudgetConfig:
    max_tokens: int = 100_000
    max_tool_calls: int = 200
    max_duration_minutes: int = 30


@dataclass
class ContextBudgetConfig:
    skills_pct: int = 35
    memory_pct: int = 10
    reasoning_pct: int = 55


@dataclass
class RoleDefinition:
    """A role configuration loaded from roles.yaml."""

    id: str
    name: str
    description: str = ""
    provider: str = ""  # empty = use default
    model: str | None = None
    skill_packs: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None  # None = all tools, [] = no tools
    output_schema: str | None = None  # references schemas/<name>.json
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    context_budget: ContextBudgetConfig = field(default_factory=ContextBudgetConfig)
    gates: list[GateConfig] = field(default_factory=list)


class RoleCatalog:
    """Loads and provides access to role definitions."""

    def __init__(self) -> None:
        self._roles: dict[str, RoleDefinition] = {}

    def load(self, path: Path) -> None:
        """Load roles from a YAML file."""
        with open(path) as f:
            raw = yaml.safe_load(f)

        for role_id, role_raw in raw.get("roles", {}).items():
            gates = []
            for g in role_raw.get("gates", []):
                gates.append(GateConfig(
                    type=g["type"],
                    threshold=g.get("threshold"),
                    command=g.get("command"),
                ))

            budget_raw = role_raw.get("budget", {})
            ctx_raw = role_raw.get("context_budget", {})

            self._roles[role_id] = RoleDefinition(
                id=role_id,
                name=role_raw.get("name", role_id),
                description=role_raw.get("description", ""),
                provider=role_raw.get("provider", ""),
                model=role_raw.get("model"),
                skill_packs=role_raw.get("skill_packs", []),
                allowed_tools=role_raw.get("allowed_tools"),
                output_schema=role_raw.get("output_schema"),
                budget=BudgetConfig(
                    max_tokens=budget_raw.get("max_tokens", 100_000),
                    max_tool_calls=budget_raw.get("max_tool_calls", 200),
                    max_duration_minutes=budget_raw.get("max_duration_minutes", 30),
                ),
                context_budget=ContextBudgetConfig(
                    skills_pct=ctx_raw.get("skills_pct", 35),
                    memory_pct=ctx_raw.get("memory_pct", 10),
                    reasoning_pct=ctx_raw.get("reasoning_pct", 55),
                ),
                gates=gates,
            )

    def get(self, role_id: str) -> RoleDefinition:
        """Get a role by ID."""
        if role_id not in self._roles:
            available = ", ".join(self._roles.keys()) or "(none)"
            raise KeyError(f"Role '{role_id}' not found. Available: {available}")
        return self._roles[role_id]

    def list_roles(self) -> list[str]:
        """List all role IDs."""
        return list(self._roles.keys())
