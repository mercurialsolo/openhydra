"""ASSISTANT.md loader — constitutional document for agent behavior."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ASSISTANT_MD = """\
# Assistant Guidelines

## Core Principles
- Be helpful, accurate, and honest
- Ask for clarification before making assumptions
- Respect user privacy and data confidentiality
- Prefer safe, reversible actions over risky ones

## Communication Style
- Be concise and direct
- Use plain language, avoid jargon unless the user does
- Acknowledge uncertainty rather than guessing

## Autonomy Guidelines
- Execute read-only tasks without asking
- Ask before making changes that are hard to reverse
- Never spend money or send messages without explicit approval

## Interests
<!-- Add topics you want the assistant to research autonomously -->
<!-- Example: -->
<!-- - AI safety research -->
<!-- - Python ecosystem updates -->
"""


def load_assistant_text(state_dir: Path | None = None) -> str:
    """Load ASSISTANT.md from global (~/.openhydra) and project-local (.openhydra).

    Returns concatenated text (global first, then local). Empty string if
    neither file exists.
    """
    sections: list[str] = []

    # Global: ~/.openhydra/ASSISTANT.md
    global_path = Path.home() / ".openhydra" / "ASSISTANT.md"
    if global_path.is_file():
        try:
            text = global_path.read_text(encoding="utf-8").strip()
            if text:
                sections.append(text)
                logger.info("Loaded global ASSISTANT.md (%d chars)", len(text))
        except OSError:
            logger.warning("Failed to read global ASSISTANT.md at %s", global_path)

    # Project-local: .openhydra/ASSISTANT.md (relative to cwd)
    local_path = Path.cwd() / ".openhydra" / "ASSISTANT.md"
    if local_path.is_file():
        try:
            text = local_path.read_text(encoding="utf-8").strip()
            if text:
                sections.append(text)
                logger.info("Loaded project ASSISTANT.md (%d chars)", len(text))
        except OSError:
            logger.warning("Failed to read project ASSISTANT.md at %s", local_path)

    return "\n\n".join(sections)


def parse_schedule(text: str) -> dict[str, str]:
    """Extract schedule settings from an ASSISTANT.md text.

    Looks for key-value pairs under a ``## Schedule`` heading.
    Format: ``- key: value`` (one per line).

    Returns a dict of schedule settings (e.g. timezone, active_hours,
    delivery_channel, owner_id).
    """
    if not text:
        return {}

    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    schedule: dict[str, str] = {}
    in_schedule_section = False

    for line in cleaned.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            in_schedule_section = stripped.lower() == "## schedule"
            continue

        if in_schedule_section and stripped.startswith("- "):
            item = stripped[2:].strip()
            if ":" in item:
                key, _, val = item.partition(":")
                key = key.strip()
                val = val.strip()
                if key and val:
                    schedule[key] = val

    return schedule


def parse_interests(text: str) -> list[str]:
    """Extract interest items from an ASSISTANT.md text.

    Looks for bullet items under a ``## Interests`` heading.
    Skips HTML comments (``<!-- ... -->``).

    Returns a list of interest strings (stripped of leading ``- ``).
    """
    if not text:
        return []

    # Strip HTML comments
    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    interests: list[str] = []
    in_interests_section = False

    for line in cleaned.splitlines():
        stripped = line.strip()

        # Detect heading transitions
        if stripped.startswith("## "):
            in_interests_section = stripped.lower() == "## interests"
            continue

        if in_interests_section and stripped.startswith("- "):
            item = stripped[2:].strip()
            if item:
                interests.append(item)

    return interests
