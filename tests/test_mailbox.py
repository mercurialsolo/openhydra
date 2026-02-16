"""Tests for Mailbox."""

from __future__ import annotations

import pytest

from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.workflow.mailbox import Mailbox


@pytest.fixture
async def mailbox(db: Database) -> Mailbox:
    return Mailbox(db=db, events=EventBus())


async def _create_workflow(db: Database, wf_id: str = "wf-001") -> str:
    """Helper to create a workflow record."""
    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES (?, 'executing', 'test')",
        (wf_id,),
    )
    await db.conn.commit()
    return wf_id


async def test_send_and_receive(mailbox: Mailbox, db: Database) -> None:
    wf_id = await _create_workflow(db)
    msg_id = await mailbox.send(wf_id, "step-0", "step-1", "Ready", "Module A is complete")
    assert msg_id is not None

    messages = await mailbox.receive(wf_id, "step-1")
    assert len(messages) == 1
    assert messages[0].subject == "Ready"
    assert messages[0].body == "Module A is complete"
    assert messages[0].from_step == "step-0"


async def test_broadcast(mailbox: Mailbox, db: Database) -> None:
    wf_id = await _create_workflow(db)
    await mailbox.send(wf_id, "step-0", None, "Update", "Broadcast message")

    # Both step-1 and step-2 should receive it
    msgs1 = await mailbox.receive(wf_id, "step-1")
    msgs2 = await mailbox.receive(wf_id, "step-2")
    assert len(msgs1) == 1
    assert len(msgs2) == 1


async def test_targeted_not_received_by_others(mailbox: Mailbox, db: Database) -> None:
    wf_id = await _create_workflow(db)
    await mailbox.send(wf_id, "step-0", "step-1", "Private", "Only for step-1")

    msgs = await mailbox.receive(wf_id, "step-2")
    assert len(msgs) == 0


async def test_mark_as_read(mailbox: Mailbox, db: Database) -> None:
    wf_id = await _create_workflow(db)
    await mailbox.send(wf_id, "step-0", "step-1", "Test", "Body")

    messages = await mailbox.receive(wf_id, "step-1")
    assert messages[0].read_at is None  # Not yet marked when returned

    # Read again — should still get the message (read_at now set in DB)
    cursor = await db.conn.execute(
        "SELECT read_at FROM messages WHERE id = ?", (messages[0].id,)
    )
    row = await cursor.fetchone()
    assert row["read_at"] is not None


async def test_list_messages(mailbox: Mailbox, db: Database) -> None:
    wf_id = await _create_workflow(db)
    await mailbox.send(wf_id, "step-0", "step-1", "Msg 1", "Body 1")
    await mailbox.send(wf_id, "step-0", "step-2", "Msg 2", "Body 2")

    all_msgs = await mailbox.list_messages(wf_id)
    assert len(all_msgs) == 2
