"""Dynamic skill builder — generates skills on-the-fly using an LLM."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .base import SkillContent, SkillMetadata

if TYPE_CHECKING:
    from ..agents.registry import AgentRegistry
    from ..events import EventBus

logger = logging.getLogger(__name__)

_GENERATION_PROMPT = """\
You are writing a procedural skill document for an AI coding agent.
Topic: "{skill_id}"

Write a SKILL.md that tells the agent exactly WHAT TO DO — not theory.

Rules:
- Use imperative voice ("Run X", "Check Y", "Add Z")
- Include concrete code examples in fenced blocks
- Use numbered steps for workflows, bullet lists for options
- Target 400-800 words (moderate length — not a one-liner, not a textbook)
- Include at least one checklist section
- NO motivational intros, NO "In conclusion" — jump straight to instructions

Output format — produce EXACTLY two sections separated by "---":

1. A YAML metadata block:
```yaml
id: {skill_id}
name: <Human-readable name>
version: "0.1.0"
tags: [<relevant>, <tags>]
priority: 2
token_estimate: <estimated tokens of SKILL.md below>
```

2. A Markdown skill document (this becomes SKILL.md).
"""

# Imperative verbs that indicate actionable, procedural content
_IMPERATIVE_VERBS = frozenset({
    "run", "check", "add", "create", "use", "set", "configure", "install",
    "define", "write", "test", "verify", "ensure", "update", "remove",
    "deploy", "build", "start", "stop", "import", "export", "call",
    "apply", "validate", "execute", "avoid", "prefer", "include",
})


def score_skill(text: str) -> dict[str, int]:
    """Score a skill document on a 0-12 heuristic rubric (no LLM call).

    Dimensions (0-3 each):
    - completeness: headings + lists present
    - clarity: imperative verb density
    - specificity: code blocks + inline code present
    - length: 300-1200 words optimal
    """
    lines = text.strip().splitlines()
    words = text.split()
    word_count = len(words)

    # Completeness: headings + lists
    heading_count = sum(1 for ln in lines if ln.strip().startswith("#"))
    list_count = sum(1 for ln in lines if re.match(r"^\s*[-*\d]+[.)]\s", ln))
    completeness = min(3, heading_count + (1 if list_count >= 3 else 0))

    # Clarity: imperative verb usage
    first_words = []
    for ln in lines:
        stripped = ln.strip().lstrip("-*0123456789.) ")
        if stripped:
            first_words.append(stripped.split()[0].lower().rstrip(".,;:"))
    imperative_count = sum(1 for w in first_words if w in _IMPERATIVE_VERBS)
    if imperative_count >= 8:
        clarity = 3
    elif imperative_count >= 4:
        clarity = 2
    elif imperative_count >= 1:
        clarity = 1
    else:
        clarity = 0

    # Specificity: code blocks + inline code
    code_block_count = text.count("```")
    inline_code_count = len(re.findall(r"`[^`]+`", text))
    if code_block_count >= 4 and inline_code_count >= 3:
        specificity = 3
    elif code_block_count >= 2 or inline_code_count >= 3:
        specificity = 2
    elif code_block_count >= 1 or inline_code_count >= 1:
        specificity = 1
    else:
        specificity = 0

    # Length: 300-1200 words optimal
    if 300 <= word_count <= 1200:
        length = 3
    elif 150 <= word_count <= 2000:
        length = 2
    elif 50 <= word_count <= 3000:
        length = 1
    else:
        length = 0

    return {
        "completeness": completeness,
        "clarity": clarity,
        "specificity": specificity,
        "length": length,
    }


class SkillBuilder:
    """Generates skills on-the-fly using an LLM when not found on disk.

    Implements the SkillSource protocol. Sits after filesystem sources in the
    registry so disk skills take priority. Only activates when no other source
    can satisfy a skill_id.
    """

    def __init__(
        self,
        agents: AgentRegistry,
        output_dir: Path,
        events: EventBus | None = None,
        quality_threshold: int = 6,
    ) -> None:
        self._agents = agents
        self._output_dir = output_dir
        self._events = events
        self._quality_threshold = quality_threshold
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for previously generated skills."""
        skills: list[SkillMetadata] = []
        if not self._output_dir.exists():
            return skills
        for meta_path in self._output_dir.glob("*/metadata.yaml"):
            try:
                raw = yaml.safe_load(meta_path.read_text())
                skills.append(SkillMetadata(
                    id=raw["id"],
                    name=raw.get("name", raw["id"]),
                    version=raw.get("version", "0.1.0"),
                    tags=raw.get("tags", []),
                    priority=raw.get("priority", 2),
                    token_estimate=raw.get("token_estimate", 0),
                    quality_score=raw.get("quality_score", 0),
                ))
            except Exception:
                logger.warning("Failed to read generated skill metadata: %s", meta_path)
        return skills

    async def load_skill(self, skill_id: str, *, summary: bool = False) -> SkillContent:
        """Load a generated skill, creating it if not already cached on disk."""
        skill_dir = self._output_dir / skill_id
        meta_path = skill_dir / "metadata.yaml"
        skill_path = skill_dir / "SKILL.md"

        # If already generated and on disk, return cached version
        if meta_path.exists() and skill_path.exists():
            return self._load_from_disk(skill_id, meta_path, skill_path)

        # Generate it
        return await self._generate(skill_id)

    async def search_skills(self, query: str) -> list[SkillMetadata]:
        """Search generated skills by keyword match on id, name, and tags."""
        all_skills = await self.list_skills()
        query_lower = query.lower()
        return [
            s for s in all_skills
            if query_lower in s.id.lower()
            or query_lower in s.name.lower()
            or any(query_lower in t.lower() for t in s.tags)
        ]

    async def _generate(self, skill_id: str) -> SkillContent:
        """Use LLM to generate SKILL.md + metadata.yaml for the given skill_id."""
        logger.info("Generating skill '%s' via LLM", skill_id)

        provider = self._agents.default()
        prompt = _GENERATION_PROMPT.format(skill_id=skill_id)

        result = await provider.run_session(
            instructions=prompt,
            system_prompt="You are a concise technical writer. Output only the requested format.",
            max_tokens=4096,
        )

        raw_text = result.raw_text
        metadata, skill_text = _parse_generation_output(raw_text, skill_id)

        # Quality gate — reject low-quality generated skills
        scores = score_skill(skill_text)
        total = sum(scores.values())

        if total < self._quality_threshold:
            logger.warning(
                "Generated skill '%s' rejected: score %d < threshold %d (%s)",
                skill_id, total, self._quality_threshold, scores,
            )
            if self._events:
                from ..events import SKILL_GENERATION_REJECTED, Event
                await self._events.emit(Event(
                    type=SKILL_GENERATION_REJECTED,
                    data={
                        "skill_id": skill_id,
                        "score": total,
                        "threshold": self._quality_threshold,
                        "breakdown": scores,
                    },
                ))
            raise KeyError(
                f"Generated skill '{skill_id}' rejected: "
                f"quality score {total} < threshold {self._quality_threshold}"
            )

        # Persist quality_score in metadata
        metadata["quality_score"] = total

        # Write to disk so FilesystemSkillSource picks it up on next scan
        skill_dir = self._output_dir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "metadata.yaml").write_text(
            yaml.safe_dump(metadata, default_flow_style=False)
        )
        (skill_dir / "SKILL.md").write_text(skill_text)

        logger.info("Generated skill '%s' → %s (quality: %d)", skill_id, skill_dir, total)

        # Emit event
        if self._events:
            from ..events import Event
            await self._events.emit(Event(
                type="skill.generated",
                data={"skill_id": skill_id, "path": str(skill_dir), "quality_score": total},
            ))

        meta = SkillMetadata(
            id=metadata["id"],
            name=metadata.get("name", skill_id),
            version=metadata.get("version", "0.1.0"),
            tags=metadata.get("tags", []),
            priority=metadata.get("priority", 2),
            token_estimate=metadata.get("token_estimate", 0),
            quality_score=total,
        )
        return SkillContent(id=skill_id, text=skill_text, metadata=meta)

    def _load_from_disk(
        self,
        skill_id: str,
        meta_path: Path,
        skill_path: Path,
    ) -> SkillContent:
        """Load a previously generated skill from disk."""
        raw = yaml.safe_load(meta_path.read_text())
        meta = SkillMetadata(
            id=raw["id"],
            name=raw.get("name", skill_id),
            version=raw.get("version", "0.1.0"),
            tags=raw.get("tags", []),
            priority=raw.get("priority", 2),
            token_estimate=raw.get("token_estimate", 0),
            quality_score=raw.get("quality_score", 0),
        )
        return SkillContent(
            id=skill_id,
            text=skill_path.read_text(),
            metadata=meta,
        )


def _parse_generation_output(raw: str, skill_id: str) -> tuple[dict, str]:
    """Parse LLM output into (metadata_dict, skill_markdown).

    Expected format: YAML block (possibly in a code fence) followed by
    a ``---`` separator and the skill markdown content.
    """
    # Strip leading/trailing whitespace
    text = raw.strip()

    # Try to split on "---" separator
    parts = text.split("\n---\n", maxsplit=1)
    if len(parts) == 2:
        yaml_part, md_part = parts
    else:
        # Fallback: try to find yaml code fence
        yaml_part = ""
        md_part = text

    # Clean up yaml part — strip code fences
    yaml_text = yaml_part.strip()
    if yaml_text.startswith("```"):
        # Remove opening fence line
        lines = yaml_text.split("\n")
        lines = lines[1:]  # skip ```yaml
        # Remove closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        yaml_text = "\n".join(lines)

    # Parse YAML metadata
    try:
        metadata = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        metadata = {}

    # Ensure required fields
    metadata.setdefault("id", skill_id)
    metadata.setdefault("name", skill_id.replace("_", " ").title())
    metadata.setdefault("version", "0.1.0")
    metadata.setdefault("tags", [])
    metadata.setdefault("priority", 2)
    metadata.setdefault("token_estimate", len(md_part.split()) * 2)

    # Clean up markdown part — strip code fences if the whole thing is wrapped
    md_text = md_part.strip()
    if md_text.startswith("```markdown") or md_text.startswith("```md"):
        lines = md_text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        md_text = "\n".join(lines)

    # If markdown is empty, use the full raw text as a fallback
    if not md_text.strip():
        md_text = raw.strip()

    return metadata, md_text
