"""Pure functions: Event → Discord Embed dictionaries."""

from __future__ import annotations

from typing import Any

from openhydra.events import Event

STATUS_COLORS = {
    "workflow.created": 0x36A64F,
    "workflow.completed": 0x36A64F,
    "workflow.failed": 0xE01E5A,
    "step.started": 0xDAA038,
    "step.completed": 0x36A64F,
    "step.failed": 0xE01E5A,
    "approval.requested": 0x4A90D9,
}


def event_to_embed(event: Event) -> dict[str, Any]:
    """Convert an engine event to a Discord embed dict.

    Returns a dict compatible with discord.Embed.from_dict().
    """
    color = STATUS_COLORS.get(event.type, 0xCCCCCC)
    title = _event_title(event)
    description = _event_description(event)

    embed: dict[str, Any] = {
        "title": title,
        "color": color,
    }

    if description:
        embed["description"] = description

    fields = _event_fields(event)
    if fields:
        embed["fields"] = fields

    return embed


def event_to_text(event: Event) -> str:
    """Plain text fallback for events."""
    return _event_title(event)


def event_to_button_labels(event: Event) -> list[dict[str, str]] | None:
    """Return button definitions for approval events, else None."""
    if event.type != "approval.requested":
        return None

    approval_id = event.data.get("approval_id", "")
    return [
        {"label": "Approve", "custom_id": f"approve:{approval_id}", "style": "green"},
        {"label": "Reject", "custom_id": f"reject:{approval_id}", "style": "red"},
    ]


def _event_title(event: Event) -> str:
    wf_id = event.data.get("workflow_id", "")[:8]

    titles = {
        "workflow.created": f"Workflow `{wf_id}` created",
        "workflow.completed": f"Workflow `{wf_id}` completed",
        "workflow.failed": f"Workflow `{wf_id}` failed",
        "step.started": f"Step started — {event.data.get('role_id', '')}",
        "step.completed": f"Step completed — {event.data.get('role_id', '')}",
        "step.failed": f"Step failed — {event.data.get('role_id', '')}",
        "approval.requested": f"Approval needed for `{wf_id}`",
    }
    return titles.get(event.type, f"Event: {event.type}")


def _event_description(event: Event) -> str:
    parts = []

    if task := event.data.get("task"):
        parts.append(f"**Task:** {task}")

    if output := event.data.get("output"):
        truncated = output[:500] + "..." if len(output) > 500 else output
        parts.append(f"```\n{truncated}\n```")

    if error := event.data.get("error"):
        parts.append(f"**Error:** {error}")

    if prompt := event.data.get("prompt"):
        parts.append(f"**Prompt:** {prompt}")

    return "\n".join(parts)


def _event_fields(event: Event) -> list[dict[str, Any]]:
    fields = []

    if (cost := event.data.get("cost_usd")) is not None:
        fields.append({"name": "Cost", "value": f"${cost:.4f}", "inline": True})

    if role := event.data.get("role_id"):
        fields.append({"name": "Role", "value": role, "inline": True})

    return fields
