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

    # --- Workflow lifecycle endpoints ---

    async def pause_workflow(request: Request) -> JSONResponse:
        wf_id = request.path_params["workflow_id"]
        try:
            await engine.pause(wf_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return JSONResponse({"status": "paused", "workflow_id": wf_id})

    async def resume_workflow(request: Request) -> JSONResponse:
        wf_id = request.path_params["workflow_id"]
        try:
            await engine.resume(wf_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return JSONResponse({"status": "resumed", "workflow_id": wf_id})

    async def cancel_workflow(request: Request) -> JSONResponse:
        wf_id = request.path_params["workflow_id"]
        try:
            await engine.cancel(wf_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return JSONResponse({"status": "cancelled", "workflow_id": wf_id})

    # --- Skill review endpoints ---

    async def list_pending_skills(_request: Request) -> JSONResponse:
        pending = await engine.list_pending_skills()
        return JSONResponse({"skills": pending})

    async def approve_skill(request: Request) -> JSONResponse:
        skill_id = request.path_params["skill_id"]
        ok = await engine.approve_skill(skill_id)
        if not ok:
            return JSONResponse({"error": "Skill not found or not pending"}, status_code=404)
        return JSONResponse({"status": "approved", "skill_id": skill_id})

    async def reject_skill(request: Request) -> JSONResponse:
        skill_id = request.path_params["skill_id"]
        ok = await engine.reject_skill(skill_id)
        if not ok:
            return JSONResponse({"error": "Skill not found or not pending"}, status_code=404)
        return JSONResponse({"status": "rejected", "skill_id": skill_id})

    # --- Auth endpoints ---

    async def confirm_auth(request: Request) -> JSONResponse:
        body = await request.json()
        code = body.get("code", "")
        if not code:
            return JSONResponse({"error": "code is required"}, status_code=400)
        # Access auth_manager from the registry stored on engine
        # The engine doesn't directly hold auth_manager, so we use a simple
        # pattern: the registry attaches it as engine._auth_manager if available
        auth_mgr = getattr(engine, "_auth_manager", None)
        if not auth_mgr:
            return JSONResponse({"error": "Auth not configured"}, status_code=501)
        ok = await auth_mgr.confirm_challenge(code)
        if not ok:
            return JSONResponse({"error": "Invalid or expired code"}, status_code=400)
        return JSONResponse({"status": "authorized"})

    async def list_auth_identities(_request: Request) -> JSONResponse:
        auth_store = getattr(engine, "_auth_store", None)
        if not auth_store:
            return JSONResponse({"identities": []})
        identities = await auth_store.list_identities()
        return JSONResponse({
            "identities": [
                {
                    "identity_key": i.identity_key,
                    "channel": i.channel,
                    "user_id": i.user_id,
                    "user_name": i.user_name,
                    "authorized_via": i.authorized_via,
                }
                for i in identities
            ],
        })

    async def revoke_auth_identity(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        auth_mgr = getattr(engine, "_auth_manager", None)
        if not auth_mgr:
            return JSONResponse({"error": "Auth not configured"}, status_code=501)
        parts = key.split(":", 1)
        if len(parts) != 2:
            return JSONResponse({"error": "Invalid key format (channel:user_id)"}, status_code=400)
        ok = await auth_mgr.revoke_identity(parts[0], parts[1])
        if not ok:
            return JSONResponse({"error": "Identity not found"}, status_code=404)
        return JSONResponse({"status": "revoked"})

    return [
        Route("/api/v1/health", health, methods=["GET"]),
        Route("/api/v1/workflows", create_workflow, methods=["POST"]),
        Route("/api/v1/workflows", list_workflows, methods=["GET"]),
        Route("/api/v1/workflows/{workflow_id}", get_workflow, methods=["GET"]),
        Route("/api/v1/approvals/{approval_id}/approve", approve_workflow, methods=["POST"]),
        Route("/api/v1/approvals/{approval_id}/reject", reject_workflow, methods=["POST"]),
        # Workflow lifecycle
        Route("/api/v1/workflows/{workflow_id}/pause", pause_workflow, methods=["POST"]),
        Route("/api/v1/workflows/{workflow_id}/resume", resume_workflow, methods=["POST"]),
        Route("/api/v1/workflows/{workflow_id}/cancel", cancel_workflow, methods=["POST"]),
        # Skill review
        Route("/api/v1/skills/pending", list_pending_skills, methods=["GET"]),
        Route("/api/v1/skills/{skill_id}/approve", approve_skill, methods=["POST"]),
        Route("/api/v1/skills/{skill_id}/reject", reject_skill, methods=["POST"]),
        # Auth
        Route("/api/v1/auth/confirm", confirm_auth, methods=["POST"]),
        Route("/api/v1/auth/identities", list_auth_identities, methods=["GET"]),
        Route("/api/v1/auth/identities/{key:path}/revoke", revoke_auth_identity, methods=["POST"]),
    ]
