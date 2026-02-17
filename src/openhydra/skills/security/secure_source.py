"""Secure skill source — wraps any SkillSource, filtering to approved skills only."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..base import SkillContent, SkillMetadata
from .models import SkillApprovalStatus

if TYPE_CHECKING:
    from ..sources.filesystem import FilesystemSkillSource
    from .pipeline import SkillSecurityPipeline

logger = logging.getLogger(__name__)


class SecureSkillSource:
    """Wraps a FilesystemSkillSource, only exposing approved skills.

    On first list_skills() call, triggers scanning for any newly discovered skills.
    Bundled skills (from the default skills path) are auto-approved.
    """

    def __init__(
        self,
        inner: FilesystemSkillSource,
        pipeline: SkillSecurityPipeline,
        *,
        is_bundled: bool = False,
    ) -> None:
        self._inner = inner
        self._pipeline = pipeline
        self._is_bundled = is_bundled
        self._initial_scan_done = False

    async def list_skills(self) -> list[SkillMetadata]:
        """List only approved skills."""
        all_skills = await self._inner.list_skills()
        if not self._initial_scan_done:
            await self._initial_scan(all_skills)
        return [s for s in all_skills if await self._is_approved(s.id)]

    async def load_skill(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        """Load a skill only if approved."""
        status = await self._pipeline.get_status(skill_id)
        if status != SkillApprovalStatus.APPROVED:
            raise KeyError(
                f"Skill '{skill_id}' is not approved (status: {status})"
            )
        return await self._inner.load_skill(skill_id, summary=summary)

    async def search_skills(self, query: str) -> list[SkillMetadata]:
        """Search only among approved skills."""
        results = await self._inner.search_skills(query)
        return [s for s in results if await self._is_approved(s.id)]

    async def _is_approved(self, skill_id: str) -> bool:
        status = await self._pipeline.get_status(skill_id)
        return status == SkillApprovalStatus.APPROVED

    async def _initial_scan(self, skills: list[SkillMetadata]) -> None:
        """Register all discovered skills, auto-approve bundled, queue scans for others."""
        self._initial_scan_done = True
        for skill in skills:
            existing = await self._pipeline.get_status(skill.id)
            if existing is not None:
                continue  # Already known

            source_path = str(self._inner.root / skill.id) if hasattr(self._inner, "root") else ""
            status = await self._pipeline.submit_for_review(
                skill.id, source_path, is_bundled=self._is_bundled,
            )

            if status == SkillApprovalStatus.PENDING_REVIEW and not self._is_bundled:
                # Queue background scan
                skill_dir = Path(source_path) if source_path else None
                if skill_dir and skill_dir.exists():
                    asyncio.create_task(
                        self._background_scan(skill.id, skill_dir),
                        name=f"skill-scan-{skill.id}",
                    )

    async def _background_scan(self, skill_id: str, skill_dir: Path) -> None:
        """Run security scan in background after engine is fully started."""
        # Small delay to let engine finish initialization
        await asyncio.sleep(0.5)
        try:
            result = await self._pipeline.run_scan(skill_id, skill_dir)
            logger.info(
                "Skill '%s' scan complete: risk=%s, auto_approved=%s",
                skill_id, result.risk_level.value, result.auto_approved,
            )
        except Exception:
            logger.exception("Background scan failed for skill '%s'", skill_id)
