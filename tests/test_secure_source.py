"""Tests for the secure skill source wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.skills.base import SkillContent, SkillMetadata
from openhydra.skills.security.pipeline import SkillSecurityPipeline
from openhydra.skills.security.secure_source import SecureSkillSource


@pytest.fixture()
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture()
def events() -> EventBus:
    return EventBus()


@pytest.fixture()
def agents() -> MagicMock:
    registry = MagicMock()
    registry.default.side_effect = RuntimeError("No providers")
    return registry


@pytest.fixture()
def pipeline(db, events, agents):
    return SkillSecurityPipeline(db, events, agents)


def _make_inner_source(skills: list[SkillMetadata]) -> MagicMock:
    """Create a mock FilesystemSkillSource."""
    source = MagicMock()
    source.root = Path("/fake/skills")
    source.list_skills = AsyncMock(return_value=skills)
    source.load_skill = AsyncMock(
        side_effect=lambda sid, **kw: SkillContent(id=sid, text=f"Content of {sid}"),
    )
    source.search_skills = AsyncMock(return_value=skills)
    return source


class TestSecureSource:
    @pytest.mark.asyncio()
    async def test_list_skills_filters_to_approved_only(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        skills = [
            SkillMetadata(id="approved-skill", name="Approved"),
            SkillMetadata(id="pending-skill", name="Pending"),
        ]
        inner = _make_inner_source(skills)
        source = SecureSkillSource(inner, pipeline, is_bundled=True)

        # Bundled source: initial scan auto-approves all
        result = await source.list_skills()
        assert len(result) == 2
        assert all(s.id in {"approved-skill", "pending-skill"} for s in result)

    @pytest.mark.asyncio()
    async def test_non_bundled_skills_not_immediately_visible(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        skills = [SkillMetadata(id="new-skill", name="New")]
        inner = _make_inner_source(skills)
        # Non-bundled: skills should be pending, not visible
        source = SecureSkillSource(inner, pipeline, is_bundled=False)

        result = await source.list_skills()
        assert len(result) == 0  # Not approved yet

    @pytest.mark.asyncio()
    async def test_load_skill_raises_for_unapproved(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        inner = _make_inner_source([])
        source = SecureSkillSource(inner, pipeline)

        # Skill not registered at all
        with pytest.raises(KeyError, match="not approved"):
            await source.load_skill("unknown-skill")

    @pytest.mark.asyncio()
    async def test_load_skill_works_for_approved(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        inner = _make_inner_source([])
        source = SecureSkillSource(inner, pipeline)

        # Manually approve
        await pipeline.submit_for_review("my-skill", "/path", is_bundled=True)

        content = await source.load_skill("my-skill")
        assert content.id == "my-skill"

    @pytest.mark.asyncio()
    async def test_search_skills_filters_to_approved(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        skills = [
            SkillMetadata(id="approved", name="Approved Skill"),
            SkillMetadata(id="pending", name="Pending Skill"),
        ]
        inner = _make_inner_source(skills)
        source = SecureSkillSource(inner, pipeline, is_bundled=True)

        # Trigger initial scan (auto-approve bundled)
        await source.list_skills()

        results = await source.search_skills("skill")
        assert len(results) == 2  # Both approved since bundled

    @pytest.mark.asyncio()
    async def test_initial_scan_only_runs_once(
        self, pipeline: SkillSecurityPipeline,
    ) -> None:
        skills = [SkillMetadata(id="skill-a", name="A")]
        inner = _make_inner_source(skills)
        source = SecureSkillSource(inner, pipeline, is_bundled=True)

        await source.list_skills()
        await source.list_skills()  # Second call

        # submit_for_review should only be called once per skill
        # Verify by checking DB has exactly one entry
        cursor = await pipeline._db.conn.execute(
            "SELECT COUNT(*) FROM skill_approvals",
        )
        row = await cursor.fetchone()
        assert row[0] == 1
