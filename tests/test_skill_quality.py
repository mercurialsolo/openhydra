"""Tests for skill quality scoring, rejection gate, and count cap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from openhydra.agents.base import SessionResult
from openhydra.events import SKILL_GENERATION_REJECTED, EventBus
from openhydra.skills.base import SkillContent, SkillMetadata
from openhydra.skills.builder import SkillBuilder, score_skill
from openhydra.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HIGH_QUALITY_SKILL = """\
# Terraform Modules

## Setup

1. Run `terraform init` to initialize the workspace
2. Create a `modules/` directory for reusable components
3. Define variables in `variables.tf`

## Best Practices

- Use `terraform fmt` before every commit
- Run `terraform validate` to check syntax
- Prefer `for_each` over `count` for named resources
- Set `required_version` in every module
- Add `description` to all variables and outputs
- Verify changes with `terraform plan` before applying

## Module Structure

```hcl
module "vpc" {
  source = "./modules/vpc"
  cidr   = var.vpc_cidr
}
```

```hcl
output "vpc_id" {
  value       = module.vpc.id
  description = "The VPC identifier"
}
```

## Checklist

- [ ] Check that all providers are pinned
- [ ] Ensure state backend is configured
- [ ] Validate module inputs have defaults
- [ ] Run `tfsec` for security scanning
- [ ] Test with `terratest` or plan output

## Common Commands

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
terraform destroy
```

Use `terraform workspace` to manage environments.
Build modules with clear input/output contracts.
Avoid hardcoded values — prefer variables for everything configurable.
Validate all inputs at the module boundary.
Deploy incrementally — one resource group at a time.
"""

LOW_QUALITY_SKILL = "This is a bad skill with no structure."

MODERATE_SKILL = """\
# Docker Tips

## Steps

- Use multi-stage builds
- Run containers as non-root
- Check image size with `docker images`
"""


# ---------------------------------------------------------------------------
# TestScoreSkill
# ---------------------------------------------------------------------------


class TestScoreSkill:
    def test_high_quality(self) -> None:
        scores = score_skill(HIGH_QUALITY_SKILL)
        total = sum(scores.values())
        assert total >= 8, f"Expected >= 8, got {total}: {scores}"
        assert scores["completeness"] >= 2
        assert scores["specificity"] >= 2

    def test_empty_text(self) -> None:
        scores = score_skill("")
        total = sum(scores.values())
        assert total == 0

    def test_blob_no_structure(self) -> None:
        blob = "word " * 500
        scores = score_skill(blob)
        assert scores["completeness"] == 0
        assert scores["clarity"] == 0
        assert scores["specificity"] == 0
        assert scores["length"] == 3  # word count is in range

    def test_too_short(self) -> None:
        scores = score_skill("# Title\n\nShort.")
        assert scores["length"] == 0

    def test_too_long(self) -> None:
        text = "# Title\n\n" + ("word " * 5000)
        scores = score_skill(text)
        assert scores["length"] == 0

    def test_moderate_length(self) -> None:
        text = "# Title\n\n" + ("word " * 200)
        scores = score_skill(text)
        assert scores["length"] == 2  # 200 words → 150-2000 bracket

    def test_imperative_verbs(self) -> None:
        text = "\n".join([
            "# Guide",
            "- Run the tests",
            "- Check the output",
            "- Add error handling",
            "- Create a module",
            "- Use dependency injection",
            "- Set the timeout",
            "- Configure logging",
            "- Install the package",
            "Some other text here to pad the word count a bit more words.",
        ])
        scores = score_skill(text)
        assert scores["clarity"] == 3


# ---------------------------------------------------------------------------
# Builder quality gate tests
# ---------------------------------------------------------------------------


def _make_builder(
    tmp_path: Path,
    raw_text: str,
    quality_threshold: int = 6,
) -> tuple[SkillBuilder, EventBus, AsyncMock]:
    """Helper: create a SkillBuilder whose LLM returns the given raw_text."""
    provider = AsyncMock()
    provider.run_session.return_value = SessionResult(
        output={},
        raw_text=raw_text,
    )
    registry = MagicMock()
    registry.default.return_value = provider
    events = EventBus()
    output_dir = tmp_path / "generated_skills"
    builder = SkillBuilder(
        agents=registry,
        output_dir=output_dir,
        events=events,
        quality_threshold=quality_threshold,
    )
    return builder, events, provider


def _wrap_llm_output(skill_text: str, skill_id: str = "test_skill") -> str:
    """Wrap skill text in the expected LLM output format (YAML + --- + markdown)."""
    return (
        f"```yaml\n"
        f"id: {skill_id}\n"
        f"name: Test Skill\n"
        f"version: '0.1.0'\n"
        f"tags: [test]\n"
        f"priority: 2\n"
        f"token_estimate: 400\n"
        f"```\n"
        f"---\n"
        f"{skill_text}"
    )


async def test_low_quality_skill_rejected(tmp_path: Path) -> None:
    builder, events, _ = _make_builder(
        tmp_path,
        _wrap_llm_output(LOW_QUALITY_SKILL),
        quality_threshold=6,
    )
    with pytest.raises(KeyError, match="rejected"):
        await builder.load_skill("test_skill")


async def test_low_quality_not_written_to_disk(tmp_path: Path) -> None:
    builder, events, _ = _make_builder(
        tmp_path,
        _wrap_llm_output(LOW_QUALITY_SKILL),
        quality_threshold=6,
    )
    with pytest.raises(KeyError):
        await builder.load_skill("test_skill")

    # No files should have been written
    output_dir = tmp_path / "generated_skills"
    skill_dir = output_dir / "test_skill"
    assert not (skill_dir / "metadata.yaml").exists()
    assert not (skill_dir / "SKILL.md").exists()


async def test_high_quality_skill_accepted(tmp_path: Path) -> None:
    builder, events, _ = _make_builder(
        tmp_path,
        _wrap_llm_output(HIGH_QUALITY_SKILL),
        quality_threshold=6,
    )
    content = await builder.load_skill("test_skill")
    assert content.id == "test_skill"
    assert "Terraform" in content.text
    assert content.metadata is not None
    assert content.metadata.quality_score >= 6


async def test_quality_score_in_metadata_yaml(tmp_path: Path) -> None:
    builder, events, _ = _make_builder(
        tmp_path,
        _wrap_llm_output(HIGH_QUALITY_SKILL),
        quality_threshold=6,
    )
    await builder.load_skill("test_skill")

    meta_path = tmp_path / "generated_skills" / "test_skill" / "metadata.yaml"
    assert meta_path.exists()
    meta = yaml.safe_load(meta_path.read_text())
    assert "quality_score" in meta
    assert meta["quality_score"] >= 6


async def test_rejection_emits_event(tmp_path: Path) -> None:
    builder, events, _ = _make_builder(
        tmp_path,
        _wrap_llm_output(LOW_QUALITY_SKILL),
        quality_threshold=6,
    )
    received: list = []

    async def handler(e):
        received.append(e)

    events.on(SKILL_GENERATION_REJECTED, handler)

    with pytest.raises(KeyError):
        await builder.load_skill("test_skill")

    assert len(received) == 1
    assert received[0].data["skill_id"] == "test_skill"
    assert received[0].data["score"] < 6
    assert "breakdown" in received[0].data


# ---------------------------------------------------------------------------
# TestSkillCountCap
# ---------------------------------------------------------------------------


class _FakeSource:
    """Minimal SkillSource that serves skills from a dict."""

    def __init__(self, skills: dict[str, SkillContent]) -> None:
        self._skills = skills

    async def list_skills(self) -> list[SkillMetadata]:
        return [s.metadata for s in self._skills.values() if s.metadata]

    async def load_skill(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        if skill_id not in self._skills:
            raise KeyError(skill_id)
        return self._skills[skill_id]

    async def search_skills(self, query: str) -> list[SkillMetadata]:
        return []


def _make_skill(skill_id: str, token_estimate: int = 100) -> SkillContent:
    meta = SkillMetadata(
        id=skill_id,
        name=skill_id.replace("_", " ").title(),
        token_estimate=token_estimate,
    )
    return SkillContent(id=skill_id, text=f"# {skill_id}", metadata=meta)


class TestSkillCountCap:
    async def test_cap_at_default_3(self) -> None:
        registry = SkillRegistry(max_skills_per_role=3)
        skills = {f"s{i}": _make_skill(f"s{i}") for i in range(5)}
        registry.add_source(_FakeSource(skills))

        loaded = await registry.provision_for_role(
            ["s0", "s1", "s2", "s3", "s4"], token_budget=10000,
        )
        assert len(loaded) == 3
        assert [s.id for s in loaded] == ["s0", "s1", "s2"]

    async def test_custom_cap(self) -> None:
        registry = SkillRegistry(max_skills_per_role=2)
        skills = {f"s{i}": _make_skill(f"s{i}") for i in range(5)}
        registry.add_source(_FakeSource(skills))

        loaded = await registry.provision_for_role(
            ["s0", "s1", "s2", "s3", "s4"], token_budget=10000,
        )
        assert len(loaded) == 2

    async def test_budget_exhaustion_before_cap(self) -> None:
        registry = SkillRegistry(max_skills_per_role=5)
        skills = {f"s{i}": _make_skill(f"s{i}", token_estimate=500) for i in range(5)}
        registry.add_source(_FakeSource(skills))

        # Budget only allows 2 skills (500 + 500 = 1000)
        loaded = await registry.provision_for_role(
            ["s0", "s1", "s2", "s3", "s4"], token_budget=1000,
        )
        assert len(loaded) == 2

    async def test_zero_cap(self) -> None:
        registry = SkillRegistry(max_skills_per_role=0)
        skills = {f"s{i}": _make_skill(f"s{i}") for i in range(3)}
        registry.add_source(_FakeSource(skills))

        loaded = await registry.provision_for_role(
            ["s0", "s1", "s2"], token_budget=10000,
        )
        assert len(loaded) == 0
