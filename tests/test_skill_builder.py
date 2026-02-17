"""Tests for dynamic SkillBuilder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from openhydra.agents.base import SessionResult
from openhydra.events import EventBus
from openhydra.skills.builder import SkillBuilder, _parse_generation_output

# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def mock_provider():
    """Mock agent provider that returns canned LLM output."""
    provider = AsyncMock()
    provider.run_session.return_value = SessionResult(
        output={},
        raw_text=(
            "```yaml\n"
            "id: terraform_modules\n"
            "name: Terraform Modules\n"
            "version: '0.1.0'\n"
            "tags: [terraform, infrastructure]\n"
            "priority: 2\n"
            "token_estimate: 400\n"
            "```\n"
            "---\n"
            "# Terraform Modules\n\n"
            "## Best Practices\n\n"
            "- Use modules for reusable infrastructure\n"
            "- Pin provider versions\n"
            "- Use `terraform fmt` before committing\n"
        ),
    )
    return provider


@pytest.fixture
def mock_agents(mock_provider):
    """Mock AgentRegistry with a sync default() returning the mock provider."""
    registry = MagicMock()
    registry.default.return_value = mock_provider
    return registry


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "generated_skills"


@pytest.fixture
def events() -> EventBus:
    return EventBus()


@pytest.fixture
def builder(mock_agents, output_dir: Path, events: EventBus) -> SkillBuilder:
    return SkillBuilder(
        agents=mock_agents, output_dir=output_dir, events=events, quality_threshold=0,
    )


# -- Unit tests for _parse_generation_output ----------------------------------


def test_parse_with_yaml_fence_and_separator() -> None:
    raw = (
        "```yaml\n"
        "id: test_skill\n"
        "name: Test Skill\n"
        "```\n"
        "---\n"
        "# Test Content\n\nSome instructions."
    )
    meta, text = _parse_generation_output(raw, "test_skill")
    assert meta["id"] == "test_skill"
    assert meta["name"] == "Test Skill"
    assert "# Test Content" in text
    assert "Some instructions." in text


def test_parse_plain_yaml_and_separator() -> None:
    raw = (
        "id: plain_skill\n"
        "name: Plain Skill\n"
        "tags: [a, b]\n"
        "---\n"
        "# Plain Content\nDetails here."
    )
    meta, text = _parse_generation_output(raw, "plain_skill")
    assert meta["id"] == "plain_skill"
    assert meta["tags"] == ["a", "b"]
    assert "# Plain Content" in text


def test_parse_no_separator_fallback() -> None:
    raw = "Just some text without yaml or separator."
    meta, text = _parse_generation_output(raw, "fallback_skill")
    assert meta["id"] == "fallback_skill"
    assert meta["name"] == "Fallback Skill"
    assert "Just some text" in text


def test_parse_defaults_filled_in() -> None:
    raw = "---\n# Content only"
    meta, text = _parse_generation_output(raw, "defaults_skill")
    assert meta["id"] == "defaults_skill"
    assert meta["version"] == "0.1.0"
    assert meta["priority"] == 2
    assert "# Content only" in text


# -- SkillBuilder integration tests -------------------------------------------


async def test_generate_writes_to_disk(builder: SkillBuilder, output_dir: Path) -> None:
    content = await builder.load_skill("terraform_modules")
    assert content.id == "terraform_modules"
    assert "Terraform" in content.text
    assert content.metadata is not None
    assert content.metadata.name == "Terraform Modules"

    # Files should exist on disk
    skill_dir = output_dir / "terraform_modules"
    assert (skill_dir / "metadata.yaml").exists()
    assert (skill_dir / "SKILL.md").exists()

    # Metadata file should be valid YAML
    meta = yaml.safe_load((skill_dir / "metadata.yaml").read_text())
    assert meta["id"] == "terraform_modules"


async def test_load_cached_skill(
    builder: SkillBuilder, output_dir: Path, mock_provider,
) -> None:
    # First call generates
    await builder.load_skill("terraform_modules")
    assert mock_provider.run_session.call_count == 1

    # Second call should read from disk (no additional LLM call)
    content = await builder.load_skill("terraform_modules")
    assert mock_provider.run_session.call_count == 1
    assert "Terraform" in content.text


async def test_list_skills_empty(builder: SkillBuilder) -> None:
    skills = await builder.list_skills()
    assert skills == []


async def test_list_skills_after_generation(builder: SkillBuilder) -> None:
    await builder.load_skill("terraform_modules")
    skills = await builder.list_skills()
    ids = {s.id for s in skills}
    assert "terraform_modules" in ids


async def test_search_skills(builder: SkillBuilder) -> None:
    await builder.load_skill("terraform_modules")
    results = await builder.search_skills("terraform")
    assert len(results) == 1
    assert results[0].id == "terraform_modules"


async def test_search_skills_no_match(builder: SkillBuilder) -> None:
    await builder.load_skill("terraform_modules")
    results = await builder.search_skills("kubernetes")
    assert results == []


async def test_emits_skill_generated_event(
    builder: SkillBuilder, events: EventBus,
) -> None:
    received: list = []

    async def handler(e):
        received.append(e)

    events.on("skill.generated", handler)

    await builder.load_skill("terraform_modules")
    assert len(received) == 1
    assert received[0].data["skill_id"] == "terraform_modules"


async def test_output_dir_created_automatically(tmp_path: Path, mock_agents) -> None:
    deep_path = tmp_path / "a" / "b" / "c" / "generated"
    SkillBuilder(agents=mock_agents, output_dir=deep_path)
    assert deep_path.exists()
