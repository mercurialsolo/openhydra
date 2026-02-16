"""Tests for Discord embed formatters — pure functions, no mocking."""

from __future__ import annotations

from openhydra.channels.discord.formatters import (
    event_to_button_labels,
    event_to_embed,
    event_to_text,
)
from openhydra.events import Event


def test_workflow_created_embed():
    event = Event(type="workflow.created", data={"workflow_id": "wf-abc", "task": "hello"})
    embed = event_to_embed(event)
    assert "title" in embed
    assert embed["color"] == 0x36A64F
    assert "wf-abc" in embed["title"]


def test_workflow_failed_embed():
    event = Event(type="workflow.failed", data={"workflow_id": "wf-1", "error": "boom"})
    embed = event_to_embed(event)
    assert embed["color"] == 0xE01E5A
    assert "boom" in embed["description"]


def test_step_completed_with_cost():
    event = Event(
        type="step.completed",
        data={"role_id": "engineer", "cost_usd": 0.05},
    )
    embed = event_to_embed(event)
    assert "engineer" in embed["title"]
    cost_fields = [f for f in embed.get("fields", []) if f["name"] == "Cost"]
    assert len(cost_fields) == 1
    assert "$0.0500" in cost_fields[0]["value"]


def test_approval_buttons():
    event = Event(
        type="approval.requested",
        data={"workflow_id": "wf-1", "approval_id": "ap-1"},
    )
    buttons = event_to_button_labels(event)
    assert buttons is not None
    assert len(buttons) == 2
    assert buttons[0]["custom_id"] == "approve:ap-1"
    assert buttons[1]["custom_id"] == "reject:ap-1"


def test_no_buttons_for_regular_events():
    event = Event(type="step.completed", data={})
    assert event_to_button_labels(event) is None


def test_event_to_text():
    event = Event(type="workflow.created", data={"workflow_id": "wf-abc"})
    text = event_to_text(event)
    assert "wf-abc" in text


def test_unknown_event_type():
    event = Event(type="custom.event", data={})
    embed = event_to_embed(event)
    assert "custom.event" in embed["title"]
    assert embed["color"] == 0xCCCCCC


def test_long_output_truncated():
    long_output = "x" * 1000
    event = Event(type="step.completed", data={"output": long_output})
    embed = event_to_embed(event)
    assert len(embed.get("description", "")) < 600
