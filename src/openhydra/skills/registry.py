"""Skill registry with multi-source support and budget-aware provisioning."""

from __future__ import annotations

from .base import SkillContent, SkillMetadata, SkillSource


class SkillRegistry:
    """Registry that aggregates skills from multiple sources."""

    def __init__(self, max_skills_per_role: int = 3) -> None:
        self._sources: list[SkillSource] = []
        self._max_skills_per_role = max_skills_per_role

    def add_source(self, source: SkillSource) -> None:
        """Add a skill source to the registry."""
        self._sources.append(source)

    async def list_all(self) -> list[SkillMetadata]:
        """List skills from all sources."""
        all_skills: list[SkillMetadata] = []
        for source in self._sources:
            skills = await source.list_skills()
            all_skills.extend(skills)
        return all_skills

    async def load(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        """Load a skill by ID, searching all sources."""
        for source in self._sources:
            try:
                return await source.load_skill(skill_id, summary=summary)
            except (KeyError, FileNotFoundError):
                continue
        raise KeyError(f"Skill '{skill_id}' not found in any source")

    async def provision_for_role(
        self,
        skill_ids: list[str],
        token_budget: int,
    ) -> list[SkillContent]:
        """Load skills for a role, respecting token budget.

        Skills are loaded in order. If a skill exceeds remaining budget,
        its summary is tried. If that also exceeds, the skill is skipped.
        """
        loaded: list[SkillContent] = []
        remaining = token_budget

        for skill_id in skill_ids:
            if len(loaded) >= self._max_skills_per_role:
                break

            try:
                skill = await self.load(skill_id)
            except KeyError:
                continue

            est = skill.metadata.token_estimate if skill.metadata else 0
            if est <= remaining:
                loaded.append(skill)
                remaining -= est
            elif skill.metadata and skill.metadata.has_summary:
                summary = await self.load(skill_id, summary=True)
                summary_est = summary.metadata.token_estimate if summary.metadata else 0
                if summary_est <= remaining:
                    loaded.append(summary)
                    remaining -= summary_est

        return loaded
