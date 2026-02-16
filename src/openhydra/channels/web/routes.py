"""REST API routes — thin wrappers around Engine methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from openhydra.engine import Engine


def build_routes(engine: Engine) -> list[Route]:
    """Build Starlette routes wired to the given engine."""

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def create_workflow(request: Request) -> JSONResponse:
        body = await request.json()
        task = body.get("task", "")
        if not task:
            return JSONResponse({"error": "task is required"}, status_code=400)
        workflow_id = await engine.submit(task)
        return JSONResponse({"workflow_id": workflow_id}, status_code=201)

    async def list_workflows(_request: Request) -> JSONResponse:
        workflows = await engine.list_workflows()
        return JSONResponse({"workflows": workflows})

    async def get_workflow(request: Request) -> JSONResponse:
        wf_id = request.path_params["workflow_id"]
        try:
            wf = await engine.get_status(wf_id)
        except Exception:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        return JSONResponse(wf)

    async def approve_workflow(request: Request) -> JSONResponse:
        approval_id = request.path_params["approval_id"]
        await engine.approve(approval_id)
        return JSONResponse({"status": "approved"})

    async def reject_workflow(request: Request) -> JSONResponse:
        approval_id = request.path_params["approval_id"]
        body = await request.json()
        reason = body.get("reason", "")
        await engine.reject(approval_id, reason)
        return JSONResponse({"status": "rejected"})

    return [
        Route("/api/v1/health", health, methods=["GET"]),
        Route("/api/v1/workflows", create_workflow, methods=["POST"]),
        Route("/api/v1/workflows", list_workflows, methods=["GET"]),
        Route("/api/v1/workflows/{workflow_id}", get_workflow, methods=["GET"]),
        Route("/api/v1/approvals/{approval_id}/approve", approve_workflow, methods=["POST"]),
        Route("/api/v1/approvals/{approval_id}/reject", reject_workflow, methods=["POST"]),
    ]
