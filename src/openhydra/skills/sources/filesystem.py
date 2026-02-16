"""Filesystem-based skill source — walks directories for SKILL.md + metadata.yaml."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from ..base import SkillContent, SkillMetadata


class FilesystemSkillSource:
    """Loads skills from a directory tree on disk.

    Each skill lives in a subdirectory containing:
    - metadata.yaml (required) — id, name, version, tags, priority, token_estimate
    - SKILL.md (required) — full skill content
    - SKILL_SUMMARY.md (optional) — shorter version for budget-constrained contexts
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[SkillMetadata, Path]] = {}

    async def list_skills(self) -> list[SkillMetadata]:
        """List all available skills by scanning the root directory."""
        await self._scan()
        return [meta for meta, _ in self._cache.values()]

    async def load_skill(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        """Load full skill content by ID."""
        await self._scan()
        if skill_id not in self._cache:
            raise KeyError(f"Skill '{skill_id}' not found in {self.root}")

        meta, skill_dir = self._cache[skill_id]

        if summary and meta.has_summary:
            text = await self._read_file(skill_dir / "SKILL_SUMMARY.md")
        else:
            text = await self._read_file(skill_dir / "SKILL.md")

        return SkillContent(id=skill_id, text=text, metadata=meta)

    async def search_skills(self, query: str) -> list[SkillMetadata]:
        """Search skills by case-insensitive substring match on name + tags."""
        await self._scan()
        query_lower = query.lower()
        results: list[SkillMetadata] = []
        for meta, _ in self._cache.values():
            if query_lower in meta.name.lower():
                results.append(meta)
                continue
            if any(query_lower in tag.lower() for tag in meta.tags):
                results.append(meta)
        return results

    async def _scan(self) -> None:
        """Scan root directory for skill subdirectories."""
        if self._cache:
            return
        await asyncio.to_thread(self._scan_sync)

    def _scan_sync(self) -> None:
        """Synchronous directory scan."""
        if not self.root.exists():
            return
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir():
                continue
            meta_path = entry / "metadata.yaml"
            skill_path = entry / "SKILL.md"
            if not meta_path.exists() or not skill_path.exists():
                continue
            try:
                meta = self._parse_metadata(meta_path, entry)
                self._cache[meta.id] = (meta, entry)
            except (yaml.YAMLError, KeyError):
                continue

    def _parse_metadata(self, meta_path: Path, skill_dir: Path) -> SkillMetadata:
        """Parse a metadata.yaml into SkillMetadata."""
        with open(meta_path) as f:
            raw = yaml.safe_load(f)
        return SkillMetadata(
            id=raw["id"],
            name=raw.get("name", raw["id"]),
            version=raw.get("version", "0.1.0"),
            tags=raw.get("tags", []),
            priority=raw.get("priority", 2),
            token_estimate=raw.get("token_estimate", 0),
            has_summary=(skill_dir / "SKILL_SUMMARY.md").exists(),
        )

    async def _read_file(self, path: Path) -> str:
        """Read a file using asyncio.to_thread."""
        return await asyncio.to_thread(path.read_text)


