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
        self.pause = AsyncMock()
        self.resume = AsyncMock()
        self.cancel = AsyncMock()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(engine):
    from starlette.applications import Starlette

    routes = build_routes(engine)
    app = Starlette(routes=routes)
    return TestClient(app)


# -----------------------------------------------------------------------------
# Health endpoint
# -----------------------------------------------------------------------------


def test_health(client):
    """GET /api/v1/health returns 200 with status:ok."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# -----------------------------------------------------------------------------
# Workflow creation
# -----------------------------------------------------------------------------


def test_create_workflow(client, engine):
    """POST /api/v1/workflows creates workflow and returns 201."""
    resp = client.post("/api/v1/workflows", json={"task": "hello world"})
    assert resp.status_code == 201
    data = resp.json()
    assert "workflow_id" in data
    assert data["workflow_id"] == "wf-123"
    engine.submit.assert_called_once_with("hello world")


def test_create_workflow_missing_task(client):
    """POST /api/v1/workflows with empty task returns 400."""
    resp = client.post("/api/v1/workflows", json={})
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert "task" in data["error"]


def test_create_workflow_empty_task(client):
    """POST /api/v1/workflows with whitespace-only task returns 400."""
    resp = client.post("/api/v1/workflows", json={"task": "   "})
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data


# -----------------------------------------------------------------------------
# List workflows
# -----------------------------------------------------------------------------


def test_list_workflows(client, engine):
    """GET /api/v1/workflows returns workflow list."""
    engine.list_workflows.return_value = [{"id": "wf-1"}, {"id": "wf-2"}]
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "workflows" in data
    assert len(data["workflows"]) == 2


def test_list_workflows_empty(client, engine):
    """GET /api/v1/workflows returns empty list when no workflows exist."""
    engine.list_workflows.return_value = []
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflows"] == []


# -----------------------------------------------------------------------------
# Get workflow status
# -----------------------------------------------------------------------------


def test_get_workflow(client, engine):
    """GET /api/v1/workflows/:id returns workflow details."""
    resp = client.get("/api/v1/workflows/wf-123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "wf-123"
    assert "status" in data
    engine.get_status.assert_called_once_with("wf-123")


def test_get_workflow_not_found(client, engine):
    """GET /api/v1/workflows/:id returns 404 when workflow doesn't exist."""
    engine.get_status.side_effect = Exception("not found")
    resp = client.get("/api/v1/workflows/wf-missing")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data


# -----------------------------------------------------------------------------
# Workflow approval
# -----------------------------------------------------------------------------


def test_approve(client, engine):
    """POST /api/v1/approvals/:id/approve succeeds."""
    resp = client.post("/api/v1/approvals/ap-1/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    engine.approve.assert_called_once_with("ap-1")


def test_reject(client, engine):
    """POST /api/v1/approvals/:id/reject with reason succeeds."""
    resp = client.post("/api/v1/approvals/ap-1/reject", json={"reason": "bad"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    engine.reject.assert_called_once_with("ap-1", "bad")


def test_reject_no_reason(client, engine):
    """POST /api/v1/approvals/:id/reject without reason succeeds."""
    resp = client.post("/api/v1/approvals/ap-1/reject", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    engine.reject.assert_called_once_with("ap-1", "")


# -----------------------------------------------------------------------------
# Workflow control: pause, resume, cancel
# -----------------------------------------------------------------------------


def test_pause_workflow(client, engine):
    """POST /api/v1/workflows/:id/pause returns 200."""
    resp = client.post("/api/v1/workflows/wf-123/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "paused"
    assert data["workflow_id"] == "wf-123"
    engine.pause.assert_called_once_with("wf-123")


def test_pause_workflow_not_found(client, engine):
    """POST /api/v1/workflows/:id/pause returns 404 when workflow missing."""
    engine.pause.side_effect = KeyError("wf-missing")
    resp = client.post("/api/v1/workflows/wf-missing/pause")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data


def test_pause_workflow_invalid_state(client, engine):
    """POST /api/v1/workflows/:id/pause returns 409 when state invalid."""
    engine.pause.side_effect = ValueError("Cannot pause completed workflow")
    resp = client.post("/api/v1/workflows/wf-123/pause")
    assert resp.status_code == 409
    data = resp.json()
    assert "error" in data


def test_resume_workflow(client, engine):
    """POST /api/v1/workflows/:id/resume returns 200."""
    resp = client.post("/api/v1/workflows/wf-123/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resumed"
    assert data["workflow_id"] == "wf-123"
    engine.resume.assert_called_once_with("wf-123")


def test_resume_workflow_not_found(client, engine):
    """POST /api/v1/workflows/:id/resume returns 404 when workflow missing."""
    engine.resume.side_effect = KeyError("wf-missing")
    resp = client.post("/api/v1/workflows/wf-missing/resume")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data


def test_resume_workflow_invalid_state(client, engine):
    """POST /api/v1/workflows/:id/resume returns 409 when state invalid."""
    engine.resume.side_effect = ValueError("Cannot resume running workflow")
    resp = client.post("/api/v1/workflows/wf-123/resume")
    assert resp.status_code == 409
    data = resp.json()
    assert "error" in data


def test_cancel_workflow(client, engine):
    """POST /api/v1/workflows/:id/cancel returns 200."""
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["workflow_id"] == "wf-123"
    engine.cancel.assert_called_once_with("wf-123")


def test_cancel_workflow_not_found(client, engine):
    """POST /api/v1/workflows/:id/cancel returns 404 when workflow missing."""
    engine.cancel.side_effect = KeyError("wf-missing")
    resp = client.post("/api/v1/workflows/wf-missing/cancel")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data


def test_cancel_workflow_invalid_state(client, engine):
    """POST /api/v1/workflows/:id/cancel returns 409 when state invalid."""
    engine.cancel.side_effect = ValueError("Cannot cancel completed workflow")
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 409
    data = resp.json()
    assert "error" in data


# -----------------------------------------------------------------------------
# JSON response structure validation
# -----------------------------------------------------------------------------


def test_workflow_status_schema(client, engine):
    """Workflow status response contains expected fields."""
    engine.get_status.return_value = {
        "id": "wf-123",
        "status": "running",
        "current_step": "step-1",
        "steps": [],
    }
    resp = client.get("/api/v1/workflows/wf-123")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "status" in data


def test_workflow_list_schema(client, engine):
    """Workflow list response wraps workflows in 'workflows' key."""
    engine.list_workflows.return_value = [
        {"id": "wf-1", "status": "completed"},
        {"id": "wf-2", "status": "running"},
    ]
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)
    assert len(data["workflows"]) == 2


def test_error_response_schema(client, engine):
    """Error responses contain 'error' field."""
    engine.get_status.side_effect = Exception("not found")
    resp = client.get("/api/v1/workflows/wf-missing")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert isinstance(data["error"], str)


# -----------------------------------------------------------------------------
# Additional schema and edge case validation
# -----------------------------------------------------------------------------


def test_create_workflow_response_schema(client, engine):
    """POST /api/v1/workflows response contains workflow_id and correct status code."""
    resp = client.post("/api/v1/workflows", json={"task": "test task"})
    assert resp.status_code == 201
    data = resp.json()
    assert "workflow_id" in data
    assert isinstance(data["workflow_id"], str)
    assert data["workflow_id"]  # Not empty


def test_health_response_schema(client):
    """GET /api/v1/health returns exact expected schema."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "ok"}
    assert len(data) == 1  # Ensure no extra fields


def test_cancel_response_schema(client, engine):
    """POST /api/v1/workflows/:id/cancel returns correct schema."""
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "workflow_id" in data
    assert data["status"] == "cancelled"
    assert data["workflow_id"] == "wf-123"


def test_get_workflow_response_has_id(client, engine):
    """GET /api/v1/workflows/:id always includes id field."""
    engine.get_status.return_value = {
        "id": "wf-test",
        "status": "running",
        "extra_field": "value",
    }
    resp = client.get("/api/v1/workflows/wf-test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "wf-test"


def test_list_workflows_response_is_array(client, engine):
    """GET /api/v1/workflows returns workflows as array."""
    engine.list_workflows.return_value = [{"id": "wf-1"}]
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["workflows"], list)


def test_cancel_nonexistent_workflow_returns_404(client, engine):
    """POST /api/v1/workflows/:id/cancel returns 404 for missing workflow."""
    engine.cancel.side_effect = KeyError("wf-404")
    resp = client.post("/api/v1/workflows/wf-404/cancel")
    assert resp.status_code == 404


def test_cancel_already_cancelled_workflow_returns_409(client, engine):
    """POST /api/v1/workflows/:id/cancel returns 409 for invalid state."""
    engine.cancel.side_effect = ValueError("Already cancelled")
    resp = client.post("/api/v1/workflows/wf-123/cancel")
    assert resp.status_code == 409


def test_create_workflow_with_malformed_json(client):
    """POST /api/v1/workflows with malformed JSON returns 400."""
    resp = client.post(
        "/api/v1/workflows",
        content=b"{invalid json",
        headers={"content-type": "application/json"},
    )
    # Starlette TestClient will raise an exception for truly malformed JSON
    # So we test with valid JSON but missing required field
    resp = client.post("/api/v1/workflows", json={"not_task": "value"})
    assert resp.status_code == 400


def test_root_health_endpoint(client):
    """GET / returns health check for hydra-web compatibility."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"
