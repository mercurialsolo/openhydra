"""Tests for web REST API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from openhydra.channels.web.routes import build_routes


class FakeEngine:
    """Minimal engine mock for route testing."""

    def __init__(self):
        self.submit = AsyncMock(return_value="wf-123")
        self.list_workflows = AsyncMock(return_value=[])
        self.get_status = AsyncMock(return_value={"id": "wf-123", "status": "completed"})
        self.approve = AsyncMock()
        self.reject = AsyncMock()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(engine):
    from starlette.applications import Starlette

    routes = build_routes(engine)
    app = Starlette(routes=routes)
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_workflow(client, engine):
    resp = client.post("/api/v1/workflows", json={"task": "hello world"})
    assert resp.status_code == 201
    assert resp.json()["workflow_id"] == "wf-123"
    engine.submit.assert_called_once_with("hello world")


def test_create_workflow_missing_task(client):
    resp = client.post("/api/v1/workflows", json={})
    assert resp.status_code == 400
    assert "task" in resp.json()["error"]


def test_list_workflows(client, engine):
    engine.list_workflows.return_value = [{"id": "wf-1"}, {"id": "wf-2"}]
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    assert len(resp.json()["workflows"]) == 2


def test_get_workflow(client, engine):
    resp = client.get("/api/v1/workflows/wf-123")
    assert resp.status_code == 200
    assert resp.json()["id"] == "wf-123"
    engine.get_status.assert_called_once_with("wf-123")


def test_get_workflow_not_found(client, engine):
    engine.get_status.side_effect = Exception("not found")
    resp = client.get("/api/v1/workflows/wf-missing")
    assert resp.status_code == 404


def test_approve(client, engine):
    resp = client.post("/api/v1/approvals/ap-1/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    engine.approve.assert_called_once_with("ap-1")


def test_reject(client, engine):
    resp = client.post("/api/v1/approvals/ap-1/reject", json={"reason": "bad"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    engine.reject.assert_called_once_with("ap-1", "bad")
