"""Pure functions: Event → Slack Block Kit JSON."""

from __future__ import annotations

from typing import Any

from openhydra.events import Event

STATUS_COLORS = {
    "workflow.created": "#36a64f",
    "workflow.completed": "#36a64f",
    "workflow.failed": "#e01e5a",
    "step.started": "#daa038",
    "step.completed": "#36a64f",
    "step.failed": "#e01e5a",
    "approval.requested": "#4a90d9",
}


def event_to_blocks(event: Event) -> list[dict[str, Any]]:
    """Convert an engine event to Slack Block Kit blocks."""
    blocks: list[dict[str, Any]] = []

    # Header
    header = _event_header(event)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": header},
    })

    # Details
    details = _event_details(event)
    if details:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": details},
        })

    # Approval buttons
    if event.type == "approval.requested":
        approval_id = event.data.get("approval_id", "")
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "approve",
                    "value": approval_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "reject",
                    "value": approval_id,
                },
            ],
        })

    return blocks


def event_to_text(event: Event) -> str:
    """Fallback plain-text representation of an event."""
    return _event_header(event)


def event_to_color(event: Event) -> str:
    """Get the sidebar color for a Slack attachment."""
    return STATUS_COLORS.get(event.type, "#cccccc")


def _event_header(event: Event) -> str:
    """Build a concise header string for the event."""
    etype = event.type
    wf_id = event.data.get("workflow_id", "")[:8]

    labels = {
        "workflow.created": f":rocket: Workflow `{wf_id}` created",
        "workflow.completed": f":white_check_mark: Workflow `{wf_id}` completed",
        "workflow.failed": f":x: Workflow `{wf_id}` failed",
        "step.started": f":gear: Step started — {event.data.get('role_id', '')}",
        "step.completed": f":white_check_mark: Step completed — {event.data.get('role_id', '')}",
        "step.failed": f":x: Step failed — {event.data.get('role_id', '')}",
        "approval.requested": f":raised_hand: Approval needed for `{wf_id}`",
    }
    return labels.get(etype, f"Event: {etype}")


def _event_details(event: Event) -> str:
    """Build detail text for the event (cost, output, etc.)."""
    parts = []

    if task := event.data.get("task"):
        parts.append(f"*Task:* {task}")

    if output := event.data.get("output"):
        truncated = output[:500] + "..." if len(output) > 500 else output
        parts.append(f"```{truncated}```")

    if error := event.data.get("error"):
        parts.append(f"*Error:* {error}")

    if (cost := event.data.get("cost_usd")) is not None:
        parts.append(f"*Cost:* ${cost:.4f}")

    if prompt := event.data.get("prompt"):
        parts.append(f"*Prompt:* {prompt}")

    return "\n".join(parts)
