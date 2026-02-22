"""Hydra API compatibility route tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.applications import Starlette
from starlette.testclient import TestClient

from openhydra.channels.web.middleware import ApiKeyMiddleware
from openhydra.channels.web.routes import build_routes
from openhydra.db import Database
from openhydra.events import EventBus


@dataclass
class _Role:
    id: str = "engineer"
    name: str = "Engineer"
    description: str = ""
    provider: str = ""
    model: str | None = None
    allowed_tools: list[str] | None = None
    skill_packs: list[str] | None = None

    class budget:  # noqa: N801
        max_tokens = 100_000
        max_tool_calls = 100
        max_duration_minutes = 30


class _Roles:
    def list_roles(self) -> list[str]:
        return ["engineer"]

    def get(self, _role_id: str) -> _Role:
        return _Role(skill_packs=[])


class FakeEngine:
    """Minimal engine mock for Hydra-compatible API testing."""

    def __init__(self):
        self.submit = AsyncMock(return_value="wf-123")
        self.list_workflows = AsyncMock(return_value=[{"id": "wf-123"}])
        self.get_status = AsyncMock(
            return_value={
                "id": "wf-123",
                "status": "executing",
                "input": "build a cli",
                "current_step": 1,
                "total_cost_usd": 0.42,
                "total_tokens": 1234,
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:01:00+00:00",
                "steps": [
                    {
                        "id": "s1",
                        "ordinal": 1,
                        "role_id": "engineer",
                        "status": "running",
                        "tokens_used": 100,
                        "cost_usd": 0.1,
                    }
                ],
            }
        )
        self.approve = AsyncMock()
        self.reject = AsyncMock()
        self.pause = AsyncMock()
        self.resume = AsyncMock(return_value="wf-123")
        self.cancel = AsyncMock()
        self.events = EventBus()
        self.roles = _Roles()
        self.config = SimpleNamespace(agents=SimpleNamespace(default_provider="openai"))


class FakeDbEngine(FakeEngine):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db


async def _seed_approval(db: Database) -> None:
    await db.conn.execute(
        "INSERT INTO workflows "
        "(id, status, input, current_step, total_cost_usd, total_tokens, created_at, "
        "updated_at, paused_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "wf-db-1",
            "waiting_approval",
            "build dashboard",
            1,
            0.0,
            0,
            "2026-02-19T00:00:00+00:00",
            "2026-02-19T00:00:00+00:00",
            "",
        ),
    )
    await db.conn.execute(
        "INSERT INTO steps (id, workflow_id, ordinal, role_id, instructions, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("step-db-1", "wf-db-1", 1, "engineer", "Do work", "running"),
    )
    await db.conn.execute(
        "INSERT INTO approvals (id, workflow_id, step_id, type, prompt, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "ap-db-1",
            "wf-db-1",
            "step-db-1",
            "approval",
            "Need your approval",
            "pending",
            "2026-02-19T00:00:30+00:00",
        ),
    )
    await db.conn.commit()


def test_hydra_login_and_workspace_flow_with_bearer_when_api_key_enabled():
    """Hydra-web bearer auth should work even when API key middleware is enabled."""
    engine = FakeEngine()
    app = Starlette(routes=build_routes(engine))
    app.add_middleware(ApiKeyMiddleware, api_key="test-secret")
    client = TestClient(app)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "pass", "workspace_id": "ws_default"},
    )
    assert login.status_code == 200
    payload = login.json()
    assert payload["token_type"] == "Bearer"
    access = payload["access_token"]

    started = client.post(
        "/workspaces/ws_default/workflows/start",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "workflow_type": "DynamicWorkflow",
            "workflow_id": "wf-ui-generated",
            "input": {"task_description": "Build a local API bridge"},
        },
    )
    assert started.status_code == 200
    assert started.json()["workflow_id"] == "wf-123"
    engine.submit.assert_called_once_with("Build a local API bridge")

    workflows = client.get(
        "/workspaces/ws_default/tasks",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert workflows.status_code == 200
    body = workflows.json()
    assert body["total"] == 1
    assert body["workflows"][0]["id"] == "wf-123"


def test_hydra_start_alias_workflows_start_uses_default_workspace():
    engine = FakeEngine()
    app = Starlette(routes=build_routes(engine))
    client = TestClient(app)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "pass"},
    )
    assert login.status_code == 200
    access = login.json()["access_token"]

    started = client.post(
        "/workflows/start",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "workflow_type": "DynamicWorkflow",
            "input": {"task_description": "Start from default workspace alias"},
        },
    )
    assert started.status_code == 200
    payload = started.json()
    assert payload["workflow_id"] == "wf-123"
    assert payload["run_id"] == "wf-123"
    assert payload["status"] == "QUEUED"
    engine.submit.assert_called_once_with("Start from default workspace alias")


def test_hydra_progress_contract_maps_waiting_approval():
    engine = FakeEngine()
    engine.get_status.return_value["status"] = "waiting_approval"
    engine.get_status.return_value["steps"][0]["status"] = "pending"

    app = Starlette(routes=build_routes(engine))
    client = TestClient(app)

    response = client.get("/workflows/wf-123/progress")
    assert response.status_code == 200
    progress = response.json()
    assert progress["status"] == "WAITING_FOR_APPROVAL"
    assert progress["steps"][0]["status"] == "waiting_approval"


def test_hydra_inbox_reads_pending_approvals_and_resolves(tmp_path: Path):
    db = Database(tmp_path / "openhydra.db")
    asyncio.run(db.connect())
    try:
        asyncio.run(_seed_approval(db))

        engine = FakeDbEngine(db)
        app = Starlette(routes=build_routes(engine))
        client = TestClient(app)

        inbox = client.get("/inbox")
        assert inbox.status_code == 200
        items = inbox.json()
        assert len(items) == 1
        assert items[0]["id"] == "ap-db-1"
        assert items[0]["workflow_id"] == "wf-db-1"
        assert items[0]["type"] == "approval"

        approved = client.post("/inbox/ap-db-1/approve", json={"decision": "approved"})
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        engine.approve.assert_called_once_with("ap-db-1")
    finally:
        asyncio.run(db.close())
