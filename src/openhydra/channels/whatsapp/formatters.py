"""Pure functions: Event → WhatsApp plain text messages."""

from __future__ import annotations

from openhydra.events import Event

STATUS_EMOJI = {
    "workflow.created": "\U0001f680",       # rocket
    "workflow.completed": "\u2705",          # check mark
    "workflow.failed": "\u274c",             # cross
    "step.started": "\u2699\ufe0f",          # gear
    "step.completed": "\u2705",
    "step.failed": "\u274c",
    "approval.requested": "\u270b",          # raised hand
}


def event_to_text(event: Event) -> str:
    """Convert an engine event to a WhatsApp text message.

    WhatsApp has limited formatting — use plain text with status emoji.
    """
    emoji = STATUS_EMOJI.get(event.type, "\U0001f4ac")  # speech bubble fallback
    header = _event_header(event, emoji)
    details = _event_details(event)

    parts = [header]
    if details:
        parts.append(details)

    return "\n".join(parts)


def _event_header(event: Event, emoji: str) -> str:
    wf_id = event.data.get("workflow_id", "")[:8]

    headers = {
        "workflow.created": f"{emoji} Workflow {wf_id} created",
        "workflow.completed": f"{emoji} Workflow {wf_id} completed",
        "workflow.failed": f"{emoji} Workflow {wf_id} failed",
        "step.started": f"{emoji} Step started: {event.data.get('role_id', '')}",
        "step.completed": f"{emoji} Step completed: {event.data.get('role_id', '')}",
        "step.failed": f"{emoji} Step failed: {event.data.get('role_id', '')}",
        "approval.requested": f"{emoji} Approval needed for {wf_id}",
    }
    return headers.get(event.type, f"{emoji} {event.type}")


def _event_details(event: Event) -> str:
    parts = []

    if task := event.data.get("task"):
        parts.append(f"Task: {task}")

    if output := event.data.get("output"):
        truncated = output[:300] + "..." if len(output) > 300 else output
        parts.append(f"Output:\n{truncated}")

    if error := event.data.get("error"):
        parts.append(f"Error: {error}")

    if (cost := event.data.get("cost_usd")) is not None:
        parts.append(f"Cost: ${cost:.4f}")

    if prompt := event.data.get("prompt"):
        parts.append(f"Prompt: {prompt}")
        parts.append("Reply 'approve' or 'reject' to respond.")

    return "\n".join(parts)
