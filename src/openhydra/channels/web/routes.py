"""REST API routes — OpenHydra legacy endpoints + Hydra-web compatibility."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from openhydra.hydra_compat import (
    HydraCompatError,
    HydraCompatService,
    issue_hydra_tokens,
    refresh_hydra_access_token,
    revoke_hydra_refresh_token,
    validate_hydra_access_token,
)

if TYPE_CHECKING:
    from openhydra.engine import Engine
    from openhydra.events import Event


def _error_response(detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {
            "error": "request_failed",
            "error_description": detail,
            "detail": detail,
            "status_code": status_code,
        },
        status_code=status_code,
    )


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        raw = await request.body()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _current_user_from_request(request: Request) -> dict[str, Any] | None:
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.query_params.get("token", "").strip()
    if not token:
        return None
    return validate_hydra_access_token(token)


def _sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _format_sse_event(event_name: str, data: dict[str, Any], event_id: int | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_name}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    lines.append("")
    return "\n".join(lines)


def _workspace_payload(workspace_id: str, *, name: str = "Default Workspace") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": workspace_id,
        "workspace_id": workspace_id,
        "name": name,
        "description": "",
        "slug": workspace_id.replace("ws_", ""),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "metadata": {},
        "settings": {
            "default_workflow_timeout_hours": 24,
            "require_approval_for_production": False,
            "auto_pause_on_risk": False,
            "notification_channels": [],
        },
    }


def build_routes(engine: Engine) -> list[Route]:
    """Build Starlette routes wired to the given engine."""

    api = HydraCompatService(engine)

    # ------------------------------------------------------------------
    # Legacy OpenHydra routes (/api/v1/*)
    # ------------------------------------------------------------------

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def create_workflow_legacy(request: Request) -> JSONResponse:
        body = await _json_body(request)
        task = str(body.get("task", "")).strip()
        if not task:
            return JSONResponse({"error": "task is required"}, status_code=400)
        workflow_id = await engine.submit(task)
        return JSONResponse({"workflow_id": workflow_id}, status_code=201)

    async def list_workflows_legacy(_request: Request) -> JSONResponse:
        workflows = await engine.list_workflows()
        return JSONResponse({"workflows": workflows})

    async def get_workflow_legacy(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            wf = await engine.get_status(workflow_id)
        except Exception:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        return JSONResponse(wf)

    async def approve_workflow_legacy(request: Request) -> JSONResponse:
        approval_id = request.path_params["approval_id"]
        await engine.approve(approval_id)
        return JSONResponse({"status": "approved"})

    async def reject_workflow_legacy(request: Request) -> JSONResponse:
        approval_id = request.path_params["approval_id"]
        body = await _json_body(request)
        reason = str(body.get("reason", ""))
        await engine.reject(approval_id, reason)
        return JSONResponse({"status": "rejected"})

    async def pause_workflow_legacy(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            await engine.pause(workflow_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse({"status": "paused", "workflow_id": workflow_id})

    async def resume_workflow_legacy(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            await engine.resume(workflow_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse({"status": "resumed", "workflow_id": workflow_id})

    async def cancel_workflow_legacy(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            await engine.cancel(workflow_id)
        except KeyError:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse({"status": "cancelled", "workflow_id": workflow_id})

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

    async def confirm_auth(request: Request) -> JSONResponse:
        body = await _json_body(request)
        code = str(body.get("code", "")).strip()
        if not code:
            return JSONResponse({"error": "code is required"}, status_code=400)
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
        return JSONResponse(
            {
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
            }
        )

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

    # ------------------------------------------------------------------
    # Hydra-web compatible routes
    # ------------------------------------------------------------------

    async def root_health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "openhydra-orchestrator"})

    async def auth_login(request: Request) -> JSONResponse:
        body = await _json_body(request)
        email = str(body.get("email", "")).strip()
        password = str(body.get("password", "")).strip()
        workspace_id = str(body.get("workspace_id") or "ws_default")

        if not email or not password:
            return _error_response("email and password are required", 400)

        payload = issue_hydra_tokens(email=email, workspace_id=workspace_id)
        return JSONResponse(payload)

    async def auth_refresh(request: Request) -> JSONResponse:
        body = await _json_body(request)
        refresh_token = str(body.get("refresh_token", "")).strip()
        if not refresh_token:
            return _error_response("refresh_token is required", 400)

        refreshed = refresh_hydra_access_token(refresh_token)
        if not refreshed:
            return _error_response("Invalid refresh token", 401)
        return JSONResponse(refreshed)

    async def auth_logout(request: Request) -> JSONResponse:
        body = await _json_body(request)
        refresh_token = str(body.get("refresh_token", "")).strip()
        if refresh_token:
            revoke_hydra_refresh_token(refresh_token)
        return JSONResponse({"success": True})

    async def auth_me(request: Request) -> JSONResponse:
        user = _current_user_from_request(request)
        if not user:
            return _error_response("Authentication required", 401)
        return JSONResponse(user)

    async def start_workspace_workflow(request: Request) -> JSONResponse:
        workspace_id = request.path_params["workspace_id"]
        body = await _json_body(request)
        try:
            started = await api.start_workflow(body, workspace_id=workspace_id)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(started)

    async def start_default_workflow(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            started = await api.start_workflow(body, workspace_id="ws_default")
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(started)

    async def list_workspace_tasks(request: Request) -> JSONResponse:
        workspace_id = request.path_params["workspace_id"]
        status = request.query_params.get("status")
        workflow_type = request.query_params.get("type") or request.query_params.get(
            "workflow_type"
        )
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
        response = await api.list_workflows(
            workspace_id=workspace_id,
            status=status,
            workflow_type=workflow_type,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(response)

    async def list_tasks(_request: Request) -> JSONResponse:
        response = await api.list_workflows()
        tasks: list[dict[str, Any]] = []
        for wf in response.get("workflows", []):
            tasks.append(
                {
                    "workflow_id": wf["id"],
                    "workflow_type": wf.get("workflow_type", "DynamicWorkflow"),
                    "task_description": str((wf.get("input") or {}).get("task_description") or ""),
                    "status": wf.get("status", "RUNNING"),
                    "domain": None,
                    "technologies": None,
                    "complexity": None,
                    "created_at": wf.get("created_at"),
                    "completed_at": wf.get("updated_at")
                    if wf.get("status") in {"COMPLETED", "FAILED", "CANCELLED", "HALTED"}
                    else None,
                    "duration_minutes": None,
                    "submitter": str((wf.get("input") or {}).get("submitter") or "user"),
                    "current_step": wf.get("current_step"),
                    "completed_steps": [
                        s.get("name") for s in wf.get("steps", []) if s.get("status") == "completed"
                    ],
                }
            )
        return JSONResponse(tasks)

    async def list_workspaces(_request: Request) -> JSONResponse:
        return JSONResponse([_workspace_payload("ws_default")])

    async def create_workspace(request: Request) -> JSONResponse:
        body = await _json_body(request)
        slug = str(body.get("slug") or "default").strip() or "default"
        name = str(body.get("name") or slug).strip() or slug
        workspace_id = f"ws_{slug}" if not slug.startswith("ws_") else slug
        return JSONResponse(_workspace_payload(workspace_id, name=name), status_code=201)

    async def get_workspace(request: Request) -> JSONResponse:
        workspace_id = request.path_params["workspace_id"]
        return JSONResponse(
            _workspace_payload(workspace_id, name=workspace_id.replace("ws_", "").title())
        )

    async def get_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            detail = await api.get_workflow(workflow_id)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(detail)

    async def get_workflow_progress(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            progress = await api.get_workflow_progress(workflow_id)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(progress)

    async def get_workflow_status(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            status_payload = await api.get_workflow_status(workflow_id)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(status_payload)

    async def approve_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        body = await _json_body(request)
        try:
            result = await api.approve_workflow(workflow_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def workflow_context(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        body = await _json_body(request)
        try:
            result = await api.add_workflow_context(workflow_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def workflow_instruct(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        body = await _json_body(request)
        try:
            result = await api.instruct_workflow(workflow_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def workflow_retry(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        body = await _json_body(request)
        try:
            result = await api.retry_workflow(workflow_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def workflow_retry_step(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        body = await _json_body(request)
        if "step_id" not in body:
            body["step_id"] = body.get("target_step_id")
        try:
            result = await api.retry_workflow(workflow_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def workflow_control(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        action = request.path_params["action"]
        body = await _json_body(request)
        reason = str(body.get("reason")) if body.get("reason") is not None else None
        try:
            result = await api.control_workflow(workflow_id, action, reason)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def list_inbox(_request: Request) -> JSONResponse:
        return JSONResponse(await api.list_inbox())

    async def get_inbox_item(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        try:
            item = await api.get_inbox_item(item_id)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(item)

    async def approve_inbox_item(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        body = await _json_body(request)
        try:
            result = await api.approve_inbox_item(item_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def reject_inbox_item(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        body = await _json_body(request)
        reason = str(body.get("reason") or body.get("feedback") or "")
        try:
            result = await api.reject_inbox_item(item_id, reason)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def context_inbox_item(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        body = await _json_body(request)
        try:
            result = await api.provide_inbox_context(item_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def credentials_inbox_item(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        body = await _json_body(request)
        try:
            result = await api.provide_inbox_credentials(item_id, body)
        except HydraCompatError as exc:
            return _error_response(exc.detail, exc.status_code)
        return JSONResponse(result)

    async def _stream_events(topics: set[str], *, workflow_id: str | None = None):
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def on_event(event: Event) -> None:
            mapped = api.map_event_to_unified_sse(event.type, event.data)
            for topic, payload, event_name in mapped:
                if topic not in topics:
                    continue
                if workflow_id and str(payload.get("workflow_id", "")) != workflow_id:
                    continue
                await queue.put((event_name, payload))

        engine.events.on_all(on_event)

        event_id = 0
        try:
            while True:
                try:
                    event_name, payload = await asyncio.wait_for(queue.get(), timeout=25)
                except asyncio.TimeoutError:
                    heartbeat = {"timestamp": datetime.now(timezone.utc).isoformat()}
                    if workflow_id:
                        heartbeat["workflow_id"] = workflow_id
                    yield _format_sse_event("heartbeat", heartbeat, event_id)
                    event_id += 1
                    continue

                yield _format_sse_event(event_name, payload, event_id)
                event_id += 1
        finally:
            engine.events._wildcard_handlers = [
                handler for handler in engine.events._wildcard_handlers if handler is not on_event
            ]

    async def stream_unified(request: Request) -> StreamingResponse:
        topics_raw = request.query_params.get("topics", "inbox,agents,tasks,workflows")
        requested = {t.strip() for t in topics_raw.split(",") if t.strip()}
        valid = {"inbox", "agents", "tasks", "workflows"}
        invalid = requested - valid
        if invalid:
            return _error_response(f"Invalid topics: {sorted(invalid)}", 400)
        if not requested:
            return _error_response("At least one topic is required", 400)

        return StreamingResponse(
            _stream_events(requested),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    async def stream_workflow(request: Request) -> StreamingResponse:
        workflow_id = request.path_params["workflow_id"]
        return StreamingResponse(
            _stream_events({"workflows"}, workflow_id=workflow_id),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    async def stream_inbox(_request: Request) -> StreamingResponse:
        return StreamingResponse(
            _stream_events({"inbox"}),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    async def stream_tasks(_request: Request) -> StreamingResponse:
        return StreamingResponse(
            _stream_events({"tasks"}),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    async def stream_agents(_request: Request) -> StreamingResponse:
        return StreamingResponse(
            _stream_events({"agents"}),
            media_type="text/event-stream",
            headers=_sse_headers(),
        )

    async def stream_workspace_workflow(request: Request) -> StreamingResponse:
        _ = request.path_params.get("workspace_id")
        return await stream_workflow(request)

    async def stream_workspace_inbox(request: Request) -> StreamingResponse:
        _ = request.path_params.get("workspace_id")
        return await stream_inbox(request)

    async def stream_workspace_tasks(request: Request) -> StreamingResponse:
        _ = request.path_params.get("workspace_id")
        return await stream_tasks(request)

    async def list_agents(_request: Request) -> JSONResponse:
        return JSONResponse(await api.list_agents())

    async def get_agent(request: Request) -> JSONResponse:
        agent_id = request.path_params["agent_id"]
        listing = await api.list_agents()
        for agent in listing["agents"]:
            if agent["id"] == agent_id:
                return JSONResponse(agent)
        return _error_response(f"Agent not found: {agent_id}", 404)

    async def list_agent_sessions(_request: Request) -> JSONResponse:
        return JSONResponse({"sessions": []})

    async def stop_agent(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "stopped"})

    async def register_agent(_request: Request) -> JSONResponse:
        return _error_response(
            "Agent registration is not available in OpenHydra compatibility mode", 501
        )

    async def agents_status(_request: Request) -> JSONResponse:
        return JSONResponse(await api.agent_status())

    async def agent_resources(_request: Request) -> JSONResponse:
        return JSONResponse({"resources": []})

    async def config_get(_request: Request) -> JSONResponse:
        return JSONResponse(await api.config_summary())

    async def config_roles(_request: Request) -> JSONResponse:
        return JSONResponse(await api.list_roles_config())

    async def config_policies_get(_request: Request) -> JSONResponse:
        return JSONResponse({"tools": []})

    async def config_policies_put(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "updated", "tools": []})

    async def config_policy_put(request: Request) -> JSONResponse:
        tool_name = request.path_params["tool_name"]
        return JSONResponse({"status": "updated", "tool_name": tool_name})

    async def config_routing(_request: Request) -> JSONResponse:
        return JSONResponse({"rules": []})

    async def audit_log(_request: Request) -> JSONResponse:
        return JSONResponse({"entries": [], "total": 0})

    async def decisions_list(_request: Request) -> JSONResponse:
        return JSONResponse({"decisions": [], "total": 0})

    async def decision_detail(request: Request) -> JSONResponse:
        decision_id = request.path_params["decision_id"]
        return _error_response(f"Decision not found: {decision_id}", 404)

    async def decision_log(_request: Request) -> JSONResponse:
        return JSONResponse({"entries": []})

    async def decision_mutate(request: Request) -> JSONResponse:
        decision_id = request.path_params["decision_id"]
        return JSONResponse({"status": "accepted", "decision_id": decision_id})

    async def model_profiles(_request: Request) -> JSONResponse:
        return JSONResponse(await api.model_profiles())

    async def list_connectors(request: Request) -> JSONResponse:
        workspace_id = request.query_params.get("workspace_id", "ws_default")
        return JSONResponse(await api.list_connectors(workspace_id=workspace_id))

    async def upsert_connector(request: Request) -> JSONResponse:
        provider = request.path_params["provider"]
        body = await _json_body(request)
        return JSONResponse(await api.upsert_connector(provider, body))

    async def connector_oauth_start(request: Request) -> JSONResponse:
        provider = request.path_params["provider"]
        body = await _json_body(request)
        return JSONResponse(await api.start_connector_oauth(provider, body))

    async def connector_oauth_complete(request: Request) -> JSONResponse:
        provider = request.path_params["provider"]
        body = await _json_body(request)
        return JSONResponse(await api.complete_connector_oauth(provider, body))

    return [
        # Root + health
        Route("/", root_health, methods=["GET"]),
        Route("/api/v1/health", health, methods=["GET"]),
        # Legacy OpenHydra endpoints
        Route("/api/v1/workflows", create_workflow_legacy, methods=["POST"]),
        Route("/api/v1/workflows", list_workflows_legacy, methods=["GET"]),
        Route("/api/v1/workflows/{workflow_id}", get_workflow_legacy, methods=["GET"]),
        Route("/api/v1/approvals/{approval_id}/approve", approve_workflow_legacy, methods=["POST"]),
        Route("/api/v1/approvals/{approval_id}/reject", reject_workflow_legacy, methods=["POST"]),
        Route("/api/v1/workflows/{workflow_id}/pause", pause_workflow_legacy, methods=["POST"]),
        Route("/api/v1/workflows/{workflow_id}/resume", resume_workflow_legacy, methods=["POST"]),
        Route("/api/v1/workflows/{workflow_id}/cancel", cancel_workflow_legacy, methods=["POST"]),
        Route("/api/v1/skills/pending", list_pending_skills, methods=["GET"]),
        Route("/api/v1/skills/{skill_id}/approve", approve_skill, methods=["POST"]),
        Route("/api/v1/skills/{skill_id}/reject", reject_skill, methods=["POST"]),
        Route("/api/v1/auth/confirm", confirm_auth, methods=["POST"]),
        Route("/api/v1/auth/identities", list_auth_identities, methods=["GET"]),
        Route("/api/v1/auth/identities/{key:path}/revoke", revoke_auth_identity, methods=["POST"]),
        # Hydra auth endpoints
        Route("/api/v1/auth/login", auth_login, methods=["POST"]),
        Route("/api/v1/auth/refresh", auth_refresh, methods=["POST"]),
        Route("/api/v1/auth/logout", auth_logout, methods=["POST"]),
        Route("/api/v1/auth/me", auth_me, methods=["GET"]),
        Route("/auth/me", auth_me, methods=["GET"]),
        # Hydra workflow endpoints
        Route(
            "/workspaces/{workspace_id}/workflows/start", start_workspace_workflow, methods=["POST"]
        ),
        Route(
            "/api/v1/workspaces/{workspace_id}/workflows/start",
            start_workspace_workflow,
            methods=["POST"],
        ),
        Route("/workflows/start", start_default_workflow, methods=["POST"]),
        Route("/api/v1/workflows/start", start_default_workflow, methods=["POST"]),
        Route("/workspaces/{workspace_id}/tasks", list_workspace_tasks, methods=["GET"]),
        Route("/api/v1/workspaces/{workspace_id}/tasks", list_workspace_tasks, methods=["GET"]),
        Route("/tasks", list_tasks, methods=["GET"]),
        Route("/workflows/{workflow_id}", get_workflow, methods=["GET"]),
        Route("/workflows/{workflow_id}/progress", get_workflow_progress, methods=["GET"]),
        Route("/workflows/{workflow_id}/status", get_workflow_status, methods=["GET"]),
        Route("/workflows/{workflow_id}/approve", approve_workflow, methods=["POST"]),
        Route("/workflows/{workflow_id}/instruct", workflow_instruct, methods=["POST"]),
        Route("/workflows/{workflow_id}/context", workflow_context, methods=["POST"]),
        Route("/workflows/{workflow_id}/retry", workflow_retry, methods=["POST"]),
        Route("/workflows/{workflow_id}/retry-step", workflow_retry_step, methods=["POST"]),
        Route("/workflows/{workflow_id}/{action}", workflow_control, methods=["POST"]),
        # Inbox
        Route("/inbox", list_inbox, methods=["GET"]),
        Route("/inbox/{item_id}", get_inbox_item, methods=["GET"]),
        Route("/inbox/{item_id}/approve", approve_inbox_item, methods=["POST"]),
        Route("/inbox/{item_id}/reject", reject_inbox_item, methods=["POST"]),
        Route("/inbox/{item_id}/context", context_inbox_item, methods=["POST"]),
        Route("/inbox/{item_id}/credentials", credentials_inbox_item, methods=["POST"]),
        # Workspaces
        Route("/api/v1/workspaces", list_workspaces, methods=["GET"]),
        Route("/api/v1/workspaces", create_workspace, methods=["POST"]),
        Route("/api/v1/workspaces/{workspace_id}", get_workspace, methods=["GET"]),
        # SSE
        Route("/stream/unified", stream_unified, methods=["GET"]),
        Route("/stream/workflows/{workflow_id}", stream_workflow, methods=["GET"]),
        Route("/stream/inbox", stream_inbox, methods=["GET"]),
        Route("/stream/tasks", stream_tasks, methods=["GET"]),
        Route("/stream/agents", stream_agents, methods=["GET"]),
        Route(
            "/api/v1/workspaces/{workspace_id}/stream/workflows/{workflow_id}",
            stream_workspace_workflow,
            methods=["GET"],
        ),
        Route(
            "/api/v1/workspaces/{workspace_id}/stream/inbox",
            stream_workspace_inbox,
            methods=["GET"],
        ),
        Route(
            "/api/v1/workspaces/{workspace_id}/stream/tasks",
            stream_workspace_tasks,
            methods=["GET"],
        ),
        # Agents
        Route("/agents", list_agents, methods=["GET"]),
        Route("/agents/{agent_id}", get_agent, methods=["GET"]),
        Route("/agents/{agent_id}/sessions", list_agent_sessions, methods=["GET"]),
        Route("/agents/{agent_id}/stop", stop_agent, methods=["POST"]),
        Route("/agents/register", register_agent, methods=["POST"]),
        Route("/agents/status", agents_status, methods=["GET"]),
        Route("/agents/resources", agent_resources, methods=["GET"]),
        # Config / policies / audit
        Route("/config", config_get, methods=["GET"]),
        Route("/config/roles", config_roles, methods=["GET"]),
        Route("/config/policies", config_policies_get, methods=["GET"]),
        Route("/config/policies", config_policies_put, methods=["PUT"]),
        Route("/config/policies/{tool_name}", config_policy_put, methods=["PUT"]),
        Route("/config/routing", config_routing, methods=["GET"]),
        Route("/audit", audit_log, methods=["GET"]),
        # Decisions (stub compatibility)
        Route("/decisions", decisions_list, methods=["GET"]),
        Route("/decisions/{decision_id}", decision_detail, methods=["GET"]),
        Route("/decisions/{decision_id}/log", decision_log, methods=["GET"]),
        Route("/decisions/{decision_id}/decide", decision_mutate, methods=["POST"]),
        Route("/decisions/{decision_id}/defer", decision_mutate, methods=["POST"]),
        Route("/decisions/{decision_id}/context", decision_mutate, methods=["POST"]),
        # Model profiles + connectors
        Route("/api/v1/model-profiles", model_profiles, methods=["GET"]),
        Route("/api/v1/connectors", list_connectors, methods=["GET"]),
        Route("/api/v1/connectors/{provider}/workspace", upsert_connector, methods=["PUT"]),
        Route(
            "/api/v1/connectors/{provider}/authorize/start",
            connector_oauth_start,
            methods=["POST"],
        ),
        Route(
            "/api/v1/connectors/{provider}/authorize/complete",
            connector_oauth_complete,
            methods=["POST"],
        ),
    ]
