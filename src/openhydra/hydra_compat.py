"""Hydra API compatibility helpers shared by web routes and CLI."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from openhydra.workflow.models import StepStatus


class HydraCompatError(Exception):
    """HTTP-like error for compatibility handlers."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Lightweight local auth token store (Hydra-web compatibility)
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat()


def _b64url(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt_like(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    return f"{_b64url(header)}.{_b64url(payload)}.{secrets.token_urlsafe(16)}"


class _TokenStore:
    def __init__(self) -> None:
        self._access: dict[str, dict[str, Any]] = {}
        self._refresh: dict[str, dict[str, Any]] = {}

    def issue(self, *, email: str, workspace_id: str = "ws_default") -> dict[str, Any]:
        now = _utc_now()
        user_name = email.split("@", 1)[0] if "@" in email else email
        user = {
            "id": f"user_{secrets.token_hex(6)}",
            "email": email,
            "name": user_name or "local-user",
            "roles": ["admin"],
            "permissions": ["*"],
            "workspace_id": workspace_id,
            "created_at": _utc_iso(),
        }

        access_exp = now + timedelta(hours=8)
        refresh_exp = now + timedelta(days=30)
        access_payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user["name"],
            "roles": user["roles"],
            "permissions": user["permissions"],
            "workspace_id": workspace_id,
            "exp": int(access_exp.timestamp()),
            "iat": int(now.timestamp()),
            "iss": "openhydra.local",
            "type": "access",
        }
        refresh_payload = {
            "sub": user["id"],
            "workspace_id": workspace_id,
            "exp": int(refresh_exp.timestamp()),
            "iat": int(now.timestamp()),
            "type": "refresh",
        }

        access_token = _jwt_like(access_payload)
        refresh_token = _jwt_like(refresh_payload)

        self._access[access_token] = {
            "user": user,
            "exp": access_exp,
        }
        self._refresh[refresh_token] = {
            "user": user,
            "exp": refresh_exp,
        }

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": int((access_exp - now).total_seconds()),
            "user": user,
        }

    def validate_access(self, token: str) -> dict[str, Any] | None:
        rec = self._access.get(token)
        if not rec:
            return None
        if rec["exp"] <= _utc_now():
            self._access.pop(token, None)
            return None
        return rec["user"]

    def refresh_access(self, refresh_token: str) -> dict[str, Any] | None:
        rec = self._refresh.get(refresh_token)
        if not rec:
            return None
        if rec["exp"] <= _utc_now():
            self._refresh.pop(refresh_token, None)
            return None

        user = rec["user"]
        now = _utc_now()
        access_exp = now + timedelta(hours=8)
        payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user["name"],
            "roles": user["roles"],
            "permissions": user.get("permissions", ["*"]),
            "workspace_id": user["workspace_id"],
            "exp": int(access_exp.timestamp()),
            "iat": int(now.timestamp()),
            "iss": "openhydra.local",
            "type": "access",
        }
        access_token = _jwt_like(payload)
        self._access[access_token] = {
            "user": user,
            "exp": access_exp,
        }
        return {
            "access_token": access_token,
            "expires_in": int((access_exp - now).total_seconds()),
        }

    def revoke_refresh(self, refresh_token: str) -> bool:
        return self._refresh.pop(refresh_token, None) is not None


_TOKEN_STORE = _TokenStore()


def issue_hydra_tokens(email: str, workspace_id: str = "ws_default") -> dict[str, Any]:
    return _TOKEN_STORE.issue(email=email, workspace_id=workspace_id)


def validate_hydra_access_token(token: str) -> dict[str, Any] | None:
    return _TOKEN_STORE.validate_access(token)


def refresh_hydra_access_token(refresh_token: str) -> dict[str, Any] | None:
    return _TOKEN_STORE.refresh_access(refresh_token)


def revoke_hydra_refresh_token(refresh_token: str) -> bool:
    return _TOKEN_STORE.revoke_refresh(refresh_token)


# ---------------------------------------------------------------------------
# Shared API compatibility service
# ---------------------------------------------------------------------------


class HydraCompatService:
    """Map OpenHydra engine behavior onto Hydra API response contracts."""

    _TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "HALTED"}

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    @staticmethod
    def workflow_status_to_hydra(status: str) -> str:
        mapping = {
            "created": "QUEUED",
            "planning": "QUEUED",
            "executing": "RUNNING",
            "waiting_approval": "WAITING_FOR_APPROVAL",
            "waiting_input": "WAITING_FOR_CORRECTION",
            "waiting_correction": "WAITING_FOR_CORRECTION",
            "paused": "PAUSED",
            "completed": "COMPLETED",
            "failed": "FAILED",
            "cancelled": "CANCELLED",
            "canceled": "CANCELLED",
            "halted": "HALTED",
            "terminated": "HALTED",
        }
        return mapping.get(str(status or "").lower(), "RUNNING")

    @staticmethod
    def step_status_to_hydra(step_status: str, *, waiting_for_approval: bool = False) -> str:
        if waiting_for_approval and step_status in {
            StepStatus.PENDING.value,
            StepStatus.RUNNING.value,
        }:
            return "waiting_approval"
        mapping = {
            "pending": "pending",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
            "skipped": "skipped",
            "waiting_approval": "waiting_approval",
            "waiting_resources": "waiting_resources",
        }
        return mapping.get(step_status, "pending")

    @staticmethod
    def extract_task_description(input_payload: dict[str, Any] | None) -> str:
        payload = input_payload or {}
        if not isinstance(payload, dict):
            return str(payload)
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        for key in (
            "task_description",
            "idea_description",
            "description",
            "task",
            "prompt",
            "goal",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        notes = context.get("notes") if isinstance(context, dict) else None
        if isinstance(notes, str) and notes.strip():
            return notes.strip()
        return ""

    @staticmethod
    def _to_input_object(raw_input: Any) -> dict[str, Any]:
        if isinstance(raw_input, dict):
            return raw_input
        if isinstance(raw_input, str):
            text = raw_input.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except Exception:
                return {
                    "task_description": text,
                    "description": text,
                }
            if isinstance(parsed, dict):
                return parsed
            return {
                "task_description": text,
                "description": text,
            }
        return {}

    async def start_workflow(
        self,
        payload: dict[str, Any],
        *,
        workspace_id: str = "ws_default",
    ) -> dict[str, Any]:
        _ = workspace_id  # single-workspace OpenHydra; retained for Hydra compat
        input_payload = payload.get("input") if isinstance(payload, dict) else {}
        task = self.extract_task_description(input_payload)
        if not task:
            raise HydraCompatError(
                400,
                "Missing task description in input.task_description (or description/task)",
            )

        workflow_id = await self.engine.submit(task)
        return {
            "workflow_id": workflow_id,
            "run_id": workflow_id,
            "status": "QUEUED",
        }

    async def _load_raw_workflow(self, workflow_id: str) -> dict[str, Any]:
        try:
            return await self.engine.get_status(workflow_id)
        except Exception as exc:
            raise HydraCompatError(404, f"Workflow not found: {workflow_id}") from exc

    @staticmethod
    def _derive_project_key(workflow_id: str, input_obj: dict[str, Any]) -> str:
        project = input_obj.get("project") or input_obj.get("project_id")
        if isinstance(project, str) and project.strip():
            return project.strip()
        if "-" in workflow_id:
            return workflow_id.split("-", 1)[0]
        return "default"

    def _workflow_response_from_raw(self, raw: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(raw.get("id", ""))
        input_obj = self._to_input_object(raw.get("input"))
        current_step_ordinal = int(raw.get("current_step") or 0)

        raw_status = str(raw.get("status", "executing"))
        hydra_status = self.workflow_status_to_hydra(raw_status)
        waiting_for_approval = hydra_status == "WAITING_FOR_APPROVAL"

        steps: list[dict[str, Any]] = []
        for s in raw.get("steps", []) or []:
            ordinal = int(s.get("ordinal") or 0)
            step_waiting = waiting_for_approval and ordinal == current_step_ordinal
            steps.append(
                {
                    "id": str(s.get("id", "")),
                    "name": f"Step {ordinal}: {s.get('role_id', 'agent')}",
                    "status": self.step_status_to_hydra(
                        str(s.get("status", "pending")), waiting_for_approval=step_waiting
                    ),
                    "agent_role": s.get("role_id"),
                    "tokens": int(s.get("tokens_used") or 0),
                    "cost_usd": float(s.get("cost_usd") or 0.0),
                    "output": s.get("output_data")
                    if isinstance(s.get("output_data"), dict)
                    else {},
                }
            )

        current_step_name = "Queued"
        if steps:
            selected = next(
                (s for s in steps if s["status"] in {"running", "waiting_approval"}), None
            )
            if selected is None and 0 < current_step_ordinal <= len(steps):
                selected = steps[current_step_ordinal - 1]
            if selected is None:
                selected = steps[min(len(steps) - 1, max(0, current_step_ordinal - 1))]
            current_step_name = str(selected.get("name") or "Running")

        created_at = str(raw.get("created_at") or _utc_iso())
        updated_at = str(raw.get("updated_at") or created_at)

        return {
            "id": workflow_id,
            "workflow_type": "DynamicWorkflow",
            "status": hydra_status,
            "current_step": current_step_name,
            "steps": steps,
            "input": input_obj,
            "output": None,
            "artifacts": [],
            "created_at": created_at,
            "updated_at": updated_at,
            "workspace_id": "ws_default",
            "project": self._derive_project_key(workflow_id, input_obj),
            "metrics": {
                "total_cost_usd": float(raw.get("total_cost_usd") or 0.0),
                "total_tokens": int(raw.get("total_tokens") or 0),
            },
        }

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        raw = await self._load_raw_workflow(workflow_id)
        return self._workflow_response_from_raw(raw)

    async def list_workflows(
        self,
        *,
        workspace_id: str = "ws_default",
        status: str | None = None,
        workflow_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        _ = workspace_id
        summaries = await self.engine.list_workflows()
        ids = [str(item.get("id", "")) for item in summaries if item.get("id")]
        if offset > 0:
            ids = ids[offset:]
        if limit > 0:
            ids = ids[:limit]

        details: list[dict[str, Any]] = []
        for wf_id in ids:
            try:
                details.append(await self.get_workflow(wf_id))
            except HydraCompatError:
                continue

        if status:
            normalized = str(status).upper()
            details = [wf for wf in details if str(wf.get("status", "")).upper() == normalized]
        if workflow_type:
            details = [wf for wf in details if wf.get("workflow_type") == workflow_type]

        return {
            "workflows": details,
            "total": len(details),
        }

    async def get_workflow_progress(self, workflow_id: str) -> dict[str, Any]:
        workflow = await self.get_workflow(workflow_id)
        steps = workflow.get("steps", [])
        total = len(steps)
        completed = len([s for s in steps if s.get("status") in {"completed", "skipped"}])
        progress = 0.0 if total == 0 else round((completed / total) * 100.0, 1)

        pending_approval = await self._first_pending_approval_payload(workflow_id)

        return {
            "workflow_id": workflow_id,
            "status": workflow["status"],
            "current_step": workflow.get("current_step") or "",
            "progress_percentage": progress,
            "steps": steps,
            "last_activity": workflow.get("updated_at") or workflow.get("created_at"),
            "artifacts": workflow.get("artifacts", []),
            "pending_approval": pending_approval,
        }

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        progress = await self.get_workflow_progress(workflow_id)
        return {
            "workflow_id": workflow_id,
            "status": {
                "state": progress["status"],
                "current_step": progress["current_step"],
                "progress_percentage": progress["progress_percentage"],
            },
        }

    async def _approval_rows(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        if not hasattr(self.engine, "db"):
            return []
        db = self.engine.db
        if db is None:
            return []

        if workflow_id:
            cursor = await db.conn.execute(
                "SELECT * FROM approvals "
                "WHERE status = 'pending' AND workflow_id = ? "
                "ORDER BY created_at ASC",
                (workflow_id,),
            )
        else:
            cursor = await db.conn.execute(
                "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC",
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def _workflow_id_for_approval(self, approval_id: str) -> str | None:
        if not hasattr(self.engine, "db"):
            return None
        cursor = await self.engine.db.conn.execute(
            "SELECT workflow_id FROM approvals WHERE id = ?",
            (approval_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return str(row["workflow_id"])

    async def _first_pending_approval_payload(self, workflow_id: str) -> dict[str, Any] | None:
        rows = await self._approval_rows(workflow_id)
        if not rows:
            return None
        row = rows[0]
        return {
            "id": str(row.get("id", "")),
            "workflow_id": str(row.get("workflow_id", workflow_id)),
            "approval_type": "DECISION_REQUIRED",
            "summary": str(row.get("prompt", "Approval required")),
            "impact_level": "medium",
            "artifacts": [],
            "created_at": str(row.get("created_at") or _utc_iso()),
        }

    async def list_inbox(self) -> list[dict[str, Any]]:
        rows = await self._approval_rows()
        items: list[dict[str, Any]] = []
        for row in rows:
            workflow_id = str(row.get("workflow_id", ""))
            step_id = str(row.get("step_id") or "")
            agent_role: str | None = None
            if step_id and hasattr(self.engine, "db"):
                cursor = await self.engine.db.conn.execute(
                    "SELECT role_id FROM steps WHERE id = ?",
                    (step_id,),
                )
                step = await cursor.fetchone()
                if step:
                    agent_role = str(step["role_id"])

            item_id = str(row.get("id", ""))
            items.append(
                {
                    "id": item_id,
                    "type": "approval",
                    "workflow_id": workflow_id,
                    "workflow_type": "DynamicWorkflow",
                    "title": "Approval Required",
                    "summary": str(row.get("prompt", "Approval required")),
                    "priority": "high",
                    "created_at": str(row.get("created_at") or _utc_iso()),
                    "artifacts": [],
                    "agent_role": agent_role,
                    "agent_recommendation": None,
                    "approval_type": "DECISION_REQUIRED",
                    "status": "pending",
                    "step_id": step_id or None,
                }
            )
        return items

    async def get_inbox_item(self, item_id: str) -> dict[str, Any]:
        items = await self.list_inbox()
        for item in items:
            if item.get("id") == item_id:
                return item
        raise HydraCompatError(404, f"Inbox item not found: {item_id}")

    async def approve_inbox_item(
        self, item_id: str, decision: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        workflow_id = await self._workflow_id_for_approval(item_id)
        if workflow_id is None:
            raise HydraCompatError(404, f"Inbox item not found: {item_id}")

        decision_value = str((decision or {}).get("decision", "approved")).lower()
        if decision_value in {"rejected", "revision_needed", "deny"}:
            reason = str((decision or {}).get("feedback") or "Rejected from inbox")
            await self.engine.reject(item_id, reason)
            return {
                "status": "rejected",
                "workflow_id": workflow_id,
                "item_id": item_id,
            }

        await self.engine.approve(item_id)
        return {
            "status": "approved",
            "workflow_id": workflow_id,
            "item_id": item_id,
        }

    async def reject_inbox_item(self, item_id: str, reason: str = "") -> dict[str, Any]:
        workflow_id = await self._workflow_id_for_approval(item_id)
        if workflow_id is None:
            raise HydraCompatError(404, f"Inbox item not found: {item_id}")

        await self.engine.reject(item_id, reason)
        return {
            "status": "rejected",
            "workflow_id": workflow_id,
            "item_id": item_id,
        }

    async def provide_inbox_context(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = await self._workflow_id_for_approval(item_id)
        if workflow_id is None:
            raise HydraCompatError(404, f"Inbox item not found: {item_id}")

        # OpenHydra approvals are binary; treat context provision as approval and continue.
        context_note = str(payload.get("content") or "")
        await self.engine.approve(item_id)
        return {
            "status": "context_provided",
            "workflow_id": workflow_id,
            "item_id": item_id,
            "message": context_note[:2000],
        }

    async def provide_inbox_credentials(
        self, item_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        workflow_id = await self._workflow_id_for_approval(item_id)
        if workflow_id is None:
            raise HydraCompatError(404, f"Inbox item not found: {item_id}")

        await self.engine.approve(item_id)
        credentials = payload.get("credentials") if isinstance(payload, dict) else None
        count = len(credentials) if isinstance(credentials, list) else 0
        return {
            "status": "credentials_provided",
            "workflow_id": workflow_id,
            "item_id": item_id,
            "credentials_count": count,
        }

    async def approve_workflow(
        self, workflow_id: str, decision: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        rows = await self._approval_rows(workflow_id)
        if not rows:
            return {
                "status": "no_pending_approval",
                "workflow_id": workflow_id,
            }
        item_id = str(rows[0].get("id"))
        result = await self.approve_inbox_item(item_id, decision)
        return {
            "status": result["status"],
            "workflow_id": workflow_id,
        }

    async def instruct_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        workflow = await self.get_workflow(workflow_id)
        instruction_type = str(payload.get("instruction_type") or "guidance")
        content = str(payload.get("content") or "").strip()
        attachments = (
            payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
        )
        target_step_id = payload.get("target_step_id")

        status = str(workflow.get("status", "RUNNING")).upper()
        if status in self._TERMINAL and content:
            followup_task = (
                f"Follow-up on workflow {workflow_id}: {content}\n"
                f"Referenced workflow status: {status}."
            )
            followup_id = await self.engine.submit(followup_task)
            return {
                "status": "followup_started",
                "workflow_id": workflow_id,
                "followup_workflow_id": followup_id,
                "instruction_type": instruction_type,
                "timestamp": _utc_iso(),
                "source_channel": str(payload.get("source_channel") or "hydra_ui"),
                "input_mode": str(payload.get("input_mode") or "text"),
                "attachment_count": len(attachments),
                "target_step_id": target_step_id,
            }

        return {
            "status": "accepted",
            "workflow_id": workflow_id,
            "instruction_type": instruction_type,
            "timestamp": _utc_iso(),
            "source_channel": str(payload.get("source_channel") or "hydra_ui"),
            "input_mode": str(payload.get("input_mode") or "text"),
            "attachment_count": len(attachments),
            "target_step_id": target_step_id,
        }

    async def add_workflow_context(
        self, workflow_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        instruction_payload = {
            "instruction_type": "guidance",
            "content": payload.get("content") or payload.get("context") or "",
            "source_channel": payload.get("instruction_channel") or "hydra_ui",
            "input_mode": payload.get("instruction_mode") or "text",
            "attachments": payload.get("files") or payload.get("links") or [],
            "target_step_id": payload.get("target_step_id"),
        }
        response = await self.instruct_workflow(workflow_id, instruction_payload)
        response["context_type"] = payload.get("context_type") or "instructions"
        return response

    async def retry_workflow(
        self, workflow_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request = payload or {}
        reason = str(request.get("reason") or "Retry requested")
        step_id = request.get("step_id")

        source = await self.get_workflow(workflow_id)
        task_desc = (
            self.extract_task_description(source.get("input") or {})
            or f"Retry workflow {workflow_id}"
        )
        if step_id:
            task_desc = f"Retry workflow {workflow_id} from step {step_id}. {reason}.\n{task_desc}"
        else:
            task_desc = f"Retry workflow {workflow_id}. {reason}.\n{task_desc}"

        followup_id = await self.engine.submit(task_desc)
        return {
            "source_workflow_id": workflow_id,
            "followup_workflow_id": followup_id,
            "status": "started",
            "action": "retry_step" if step_id else "retry",
            "retried_step_id": step_id,
            "budget_overrides": request.get("budget_overrides"),
        }

    async def control_workflow(
        self, workflow_id: str, action: str, reason: str | None = None
    ) -> dict[str, Any]:
        action = action.lower().strip()
        try:
            if action == "pause":
                await self.engine.pause(workflow_id)
                return {
                    "workflow_id": workflow_id,
                    "action": action,
                    "status": "paused",
                    "temporal_status": "RUNNING",
                    "message": reason,
                }

            if action == "resume":
                await self.engine.resume(workflow_id)
                return {
                    "workflow_id": workflow_id,
                    "action": action,
                    "status": "running",
                    "temporal_status": "RUNNING",
                    "message": reason,
                }

            if action in {"cancel", "terminate"}:
                await self.engine.cancel(workflow_id)
                return {
                    "workflow_id": workflow_id,
                    "action": action,
                    "status": "cancel_requested" if action == "cancel" else "terminated",
                    "temporal_status": "CANCELED",
                    "message": reason,
                }

            raise HydraCompatError(400, f"Unsupported workflow action: {action}")

        except KeyError as exc:
            raise HydraCompatError(404, f"Workflow not found: {workflow_id}") from exc
        except ValueError as exc:
            message = str(exc)
            lowered = message.lower()
            if action == "pause" and "cannot pause" in lowered and "paused" in lowered:
                return {
                    "workflow_id": workflow_id,
                    "action": action,
                    "status": "already_paused",
                    "temporal_status": "RUNNING",
                    "message": message,
                }
            if action == "resume" and "cannot resume" in lowered:
                return {
                    "workflow_id": workflow_id,
                    "action": action,
                    "status": "already_running",
                    "temporal_status": "RUNNING",
                    "message": message,
                }
            raise HydraCompatError(409, message) from exc

    # ------------------------------------------------------------------
    # Optional/stub endpoints used by Hydra web settings pages
    # ------------------------------------------------------------------

    async def list_agents(self) -> dict[str, Any]:
        roles = []
        try:
            role_ids = list(self.engine.roles.list_roles())
        except Exception:
            role_ids = []

        now = _utc_iso()
        for role_id in role_ids:
            roles.append(
                {
                    "id": role_id,
                    "role_id": role_id,
                    "queue": "default",
                    "status": "idle",
                    "agent_type": "standard",
                    "provider": getattr(self.engine.config.agents, "default_provider", "local"),
                    "model": None,
                    "execution_isolation": "process",
                    "active_workflows": [],
                    "active_sessions": 0,
                    "total_sessions": 0,
                    "total_tokens_used": 0,
                    "uptime_seconds": 0,
                    "last_activity": now,
                    "last_heartbeat": now,
                    "error_rate": 0,
                    "skill_packs": [],
                    "allowed_tools": [],
                    "permission_mode": "ask",
                }
            )

        return {"agents": roles}

    async def agent_status(self) -> dict[str, int]:
        listing = await self.list_agents()
        agents = listing.get("agents", [])
        active = len([a for a in agents if a.get("status") == "active"])
        idle = len([a for a in agents if a.get("status") == "idle"])
        error = len([a for a in agents if a.get("status") == "error"])
        return {
            "total": len(agents),
            "active": active,
            "idle": idle,
            "error": error,
        }

    async def list_roles_config(self) -> dict[str, Any]:
        roles: list[dict[str, Any]] = []
        for role_id in self.engine.roles.list_roles():
            role = self.engine.roles.get(role_id)
            roles.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "provider": role.provider or self.engine.config.agents.default_provider,
                    "model": role.model,
                    "allowed_tools": role.allowed_tools or [],
                    "skill_packs": role.skill_packs,
                    "budget": {
                        "max_tokens": role.budget.max_tokens,
                        "max_tool_calls": role.budget.max_tool_calls,
                        "max_duration_minutes": role.budget.max_duration_minutes,
                    },
                }
            )
        return {"roles": roles}

    async def config_summary(self) -> dict[str, Any]:
        return {
            "policies": {"tools": []},
            "routing": {"rules": []},
            "roles": (await self.list_roles_config())["roles"],
        }

    async def model_profiles(self) -> dict[str, Any]:
        default_provider = getattr(self.engine.config.agents, "default_provider", "openhydra")
        return {
            "providers": [
                {
                    "provider": default_provider,
                    "label": default_provider,
                    "default_model": "default",
                    "capabilities": {
                        "supports_mcp": True,
                        "supports_resume_fork": False,
                        "supports_tool_events": True,
                    },
                    "models": [
                        {"id": "default", "label": "default", "legacy": False},
                    ],
                },
            ],
            "routing_mode": "single_provider",
        }

    async def list_connectors(self, workspace_id: str = "ws_default") -> list[dict[str, Any]]:
        return [
            {
                "provider": "openai",
                "workspace_id": workspace_id,
                "auth_mode": "workspace_secret",
                "status": "inactive",
                "scopes": [],
                "secret_ref": None,
                "secret_ref_keys": [],
                "metadata": {},
                "user_grant_status": None,
                "user_grant_scopes": [],
                "user_grant_expires_at": None,
            },
            {
                "provider": "anthropic",
                "workspace_id": workspace_id,
                "auth_mode": "workspace_secret",
                "status": "inactive",
                "scopes": [],
                "secret_ref": None,
                "secret_ref_keys": [],
                "metadata": {},
                "user_grant_status": None,
                "user_grant_scopes": [],
                "user_grant_expires_at": None,
            },
        ]

    async def upsert_connector(self, provider: str, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(payload.get("workspace_id") or "ws_default")
        return {
            "provider": provider,
            "workspace_id": workspace_id,
            "auth_mode": str(payload.get("auth_mode") or "workspace_secret"),
            "status": str(payload.get("status") or "active"),
            "scopes": payload.get("scopes") if isinstance(payload.get("scopes"), list) else [],
            "secret_ref": payload.get("secret_ref"),
            "secret_ref_keys": sorted((payload.get("secret_refs") or {}).keys())
            if isinstance(payload.get("secret_refs"), dict)
            else [],
            "metadata": payload.get("metadata")
            if isinstance(payload.get("metadata"), dict)
            else {},
            "user_grant_status": None,
            "user_grant_scopes": [],
            "user_grant_expires_at": None,
        }

    async def start_connector_oauth(self, provider: str, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(payload.get("workspace_id") or "ws_default")
        state = secrets.token_urlsafe(16)
        expires_at = (_utc_now() + timedelta(minutes=10)).isoformat()
        return {
            "provider": provider,
            "workspace_id": workspace_id,
            "authorization_url": f"https://example.local/oauth/{provider}?state={state}",
            "state": state,
            "expires_at": expires_at,
            "status": "pending_user_authorization",
        }

    async def complete_connector_oauth(
        self, provider: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        workspace_id = str(payload.get("workspace_id") or "ws_default")
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
        return {
            "provider": provider,
            "workspace_id": workspace_id,
            "status": "authorized",
            "scopes": scopes,
            "expires_at": None,
        }

    @staticmethod
    def map_event_to_unified_sse(
        event_type: str, data: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Return (topic, payload, event_name) tuples for a raw engine event."""
        out: list[tuple[str, dict[str, Any], str]] = []
        workflow_id = data.get("workflow_id")

        if event_type.startswith("workflow."):
            payload = {"workflow_id": workflow_id, **data, "timestamp": _utc_iso()}
            if event_type == "workflow.created":
                out.append(("tasks", payload, "task.created"))
            elif event_type == "workflow.completed":
                out.append(("tasks", payload, "task.completed"))
                out.append(("workflows", payload, "workflow.completed"))
            else:
                out.append(("tasks", payload, "task.status_changed"))
                out.append(("workflows", payload, "workflow.updated"))

        if event_type.startswith("step."):
            payload = {"workflow_id": workflow_id, **data, "timestamp": _utc_iso()}
            out.append(("workflows", payload, "workflow.step_changed"))
            out.append(("tasks", payload, "task.status_changed"))

        if event_type == "approval.requested":
            payload = {"workflow_id": workflow_id, **data, "timestamp": _utc_iso()}
            out.append(("inbox", payload, "inbox.new_item"))
            out.append(("workflows", payload, "workflow.approval_requested"))

        if event_type == "approval.resolved":
            payload = {"workflow_id": workflow_id, **data, "timestamp": _utc_iso()}
            out.append(("inbox", payload, "inbox.item_resolved"))

        return out

    async def start_followup_workflow(
        self, workflow_id: str, prompt: str, *, suffix: str = ""
    ) -> dict[str, Any]:
        task = f"Follow-up for {workflow_id}{suffix}: {prompt}".strip()
        followup_id = await self.engine.submit(task)
        return {
            "source_workflow_id": workflow_id,
            "followup_workflow_id": followup_id,
            "status": "started",
        }

    @staticmethod
    def create_workflow_id(prefix: str = "wf") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:10]}"
