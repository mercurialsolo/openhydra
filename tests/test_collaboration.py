"""Integration tests for collaboration features — workspace + mailbox + parallel execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openhydra.agents.base import SessionResult
from openhydra.db import Database
from openhydra.events import EventBus
from openhydra.roles.catalog import RoleCatalog
from openhydra.workflow.engine import WorkflowEngine
from openhydra.workflow.mailbox import Mailbox
from openhydra.workflow.models import Step
from openhydra.workflow.workspace import Workspace


@pytest.fixture
def roles() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.load(Path(__file__).parent.parent / "config" / "agents.yaml")
    return catalog


async def test_parallel_steps_with_shared_workspace(
    db: Database, tmp_path: Path, roles: RoleCatalog
) -> None:
    """Two parallel implementation steps followed by a review."""
    events = EventBus()
    workspace = Workspace("collab-test", tmp_path, events)

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value=SessionResult(
        output={"text": "done", "quality_score": 30},
        raw_text="done",
        tokens_used=100,
        cost_usd=0.01,
    ))

    engine = WorkflowEngine(
        db=db, events=events, role_executor=mock_executor, roles=roles,
        max_retries=1, max_concurrent=3,
    )

    # DAG: plan -> (impl A || impl B) -> review
    steps = [
        Step(role_id="planner", instructions="Plan the modules"),
        Step(role_id="eng.implement", instructions="Build module A", depends_on=[0]),
        Step(role_id="eng.implement", instructions="Build module B", depends_on=[0]),
        Step(role_id="pm.review", instructions="Review both modules", depends_on=[1, 2]),
    ]

    wf_id = await engine.create_workflow("Parallel collab", steps)
    await engine.execute_workflow(wf_id)

    wf = await engine.get_workflow(wf_id)
    assert wf["status"] == "completed"
    assert mock_executor.execute.call_count == 4

    # Workspace can track artifacts
    workspace.register_artifact("module_a.py", b"def a(): pass")
    workspace.register_artifact("module_b.py", b"def b(): pass")
    assert len(workspace.list_artifacts()) == 2


async def test_mailbox_message_flow(db: Database) -> None:
    """Messages from one step can be retrieved by another."""
    events = EventBus()
    mailbox = Mailbox(db=db, events=events)

    # Create workflow
    await db.conn.execute(
        "INSERT INTO workflows (id, status, input) VALUES ('mbox-test', 'executing', 'test')"
    )
    await db.conn.commit()

    # Step 0 sends result to step 1
    await mailbox.send("mbox-test", "step-0", "step-1", "Architecture", "Use factory pattern")

    # Step 0 broadcasts to all
    await mailbox.send("mbox-test", "step-0", None, "Update", "Scaffold complete")

    # Step 1 receives both targeted and broadcast
    messages = await mailbox.receive("mbox-test", "step-1")
    assert len(messages) == 2
    subjects = {m.subject for m in messages}
    assert "Architecture" in subjects
    assert "Update" in subjects

    # Step 2 only receives broadcast
    messages = await mailbox.receive("mbox-test", "step-2")
    assert len(messages) == 1
    assert messages[0].subject == "Update"
