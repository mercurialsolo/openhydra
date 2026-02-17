"""Skill source protocol and content types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SkillMetadata:
    """Metadata about a skill without loading its content."""

    id: str
    name: str
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    priority: int = 2  # 0=core, 1=matched, 2=supplementary
    token_estimate: int = 0  # approximate token count
    has_summary: bool = False
    quality_score: int = 0  # 0 = unscored, 1-12 = heuristic quality rating


@dataclass
class SkillContent:
    """Full skill content loaded from a source."""

    id: str
    text: str  # SKILL.md content (or SKILL_SUMMARY.md if summary=True)
    templates: dict[str, str] = field(default_factory=dict)  # filename -> content
    scripts: dict[str, str] = field(default_factory=dict)  # filename -> content
    metadata: SkillMetadata | None = None


@runtime_checkable
class SkillSource(Protocol):
    """Protocol for pluggable skill sources."""

    async def list_skills(self) -> list[SkillMetadata]:
        """List all available skills from this source."""
        ...

    async def load_skill(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        """Load full skill content by ID.

        If summary=True and a SKILL_SUMMARY.md exists, return that instead.
        """
        ...

    async def search_skills(self, query: str) -> list[SkillMetadata]:
        """Search skills by keyword/tag matching."""
        ...
