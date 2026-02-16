"""Tests for FilesystemSkillSource."""

from __future__ import annotations

from pathlib import Path

import pytest

from openhydra.skills.sources.filesystem import FilesystemSkillSource


@pytest.fixture
def skills_dir() -> Path:
    """Path to the bundled skills directory."""
    return Path(__file__).parent.parent / "skills"


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    """Empty directory with no skills."""
    return tmp_path / "empty_skills"


@pytest.fixture
def skill_dir_with_summary(tmp_path: Path) -> Path:
    """Skill directory with both SKILL.md and SKILL_SUMMARY.md."""
    skill = tmp_path / "summarized_skill"
    skill.mkdir()
    (skill / "metadata.yaml").write_text(
        "id: summarized\nname: Summarized Skill\ntags: [test]\ntoken_estimate: 500\n"
    )
    (skill / "SKILL.md").write_text("# Full Content\nThis is the full skill.")
    (skill / "SKILL_SUMMARY.md").write_text("# Summary\nShort version.")
    return tmp_path


@pytest.fixture
def source(skills_dir: Path) -> FilesystemSkillSource:
    return FilesystemSkillSource(skills_dir)


async def test_list_skills(source: FilesystemSkillSource) -> None:
    skills = await source.list_skills()
    ids = {s.id for s in skills}
    assert "eng_harness" in ids
    assert "coding_principles" in ids
    assert len(skills) >= 2


async def test_load_skill(source: FilesystemSkillSource) -> None:
    content = await source.load_skill("coding_principles")
    assert content.id == "coding_principles"
    assert "Coding Principles" in content.text
    assert content.metadata is not None
    assert content.metadata.name == "Coding Principles"


async def test_load_skill_not_found(source: FilesystemSkillSource) -> None:
    with pytest.raises(KeyError, match="nonexistent"):
        await source.load_skill("nonexistent")


async def test_search_by_tag(source: FilesystemSkillSource) -> None:
    results = await source.search_skills("engineering")
    ids = {s.id for s in results}
    assert "eng_harness" in ids
    assert "coding_principles" in ids


async def test_search_by_name(source: FilesystemSkillSource) -> None:
    results = await source.search_skills("harness")
    ids = {s.id for s in results}
    assert "eng_harness" in ids


async def test_search_case_insensitive(source: FilesystemSkillSource) -> None:
    results = await source.search_skills("CODING")
    ids = {s.id for s in results}
    assert "coding_principles" in ids


async def test_empty_directory(empty_dir: Path) -> None:
    source = FilesystemSkillSource(empty_dir)
    skills = await source.list_skills()
    assert skills == []


async def test_load_summary(skill_dir_with_summary: Path) -> None:
    source = FilesystemSkillSource(skill_dir_with_summary)
    content = await source.load_skill("summarized", summary=True)
    assert "Short version" in content.text


async def test_load_full_when_no_summary(source: FilesystemSkillSource) -> None:
    content = await source.load_skill("coding_principles", summary=True)
    # No summary exists, so full content is returned
    assert "Coding Principles" in content.text
