"""Tests for Slack Block Kit formatters — pure functions, no mocking."""

from __future__ import annotations

from openhydra.channels.slack.formatters import (
    event_to_blocks,
    event_to_color,
    event_to_text,
)
from openhydra.events import Event


def test_workflow_created_blocks():
    event = Event(type="workflow.created", data={"workflow_id": "wf-12345678", "task": "hello"})
    blocks = event_to_blocks(event)
    assert len(blocks) >= 1
    # First block is header
    assert "rocket" in blocks[0]["text"]["text"].lower() or "wf-12345" in blocks[0]["text"]["text"]


def test_approval_requested_has_buttons():
    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1", "prompt": "Approve this?"},
    )
    blocks = event_to_blocks(event)
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    buttons = action_blocks[0]["elements"]
    assert len(buttons) == 2
    assert buttons[0]["action_id"] == "approve"
    assert buttons[0]["value"] == "ap-1"
    assert buttons[1]["action_id"] == "reject"


def test_step_completed_with_output():
    event = Event(
        type="step.completed",
        data={"role_id": "engineer", "output": "done", "cost_usd": 0.05},
    )
    blocks = event_to_blocks(event)
    texts = " ".join(b.get("text", {}).get("text", "") for b in blocks)
    assert "engineer" in texts
    assert "$0.0500" in texts


def test_step_failed_with_error():
    event = Event(type="step.failed", data={"role_id": "test", "error": "boom"})
    blocks = event_to_blocks(event)
    texts = " ".join(b.get("text", {}).get("text", "") for b in blocks)
    assert "boom" in texts


def test_event_to_text_fallback():
    event = Event(type="workflow.created", data={"workflow_id": "wf-abc"})
    text = event_to_text(event)
    assert "wf-abc" in text


def test_event_to_color():
    assert event_to_color(Event(type="workflow.completed", data={})) == "#36a64f"
    assert event_to_color(Event(type="workflow.failed", data={})) == "#e01e5a"
    assert event_to_color(Event(type="unknown.event", data={})) == "#cccccc"


def test_long_output_truncated():
    long_output = "x" * 1000
    event = Event(type="step.completed", data={"output": long_output})
    blocks = event_to_blocks(event)
    detail_text = blocks[1]["text"]["text"]
    assert len(detail_text) < 600
    assert "..." in detail_text


def test_unknown_event_type():
    event = Event(type="custom.event", data={"foo": "bar"})
    blocks = event_to_blocks(event)
    assert len(blocks) >= 1
    assert "custom.event" in blocks[0]["text"]["text"]
