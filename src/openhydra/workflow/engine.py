"""Workflow engine — DAG-based execution with state persistence and gating."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Database
from ..events import (
    APPROVAL_REQUESTED,
    COST_UPDATED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_STARTED,
    WORKFLOW_COMPLETED,
    WORKFLOW_CREATED,
    WORKFLOW_EXECUTING,
    WORKFLOW_FAILED,
    Event,
    EventBus,
)
from ..gates.base import Gate
from ..roles.catalog import RoleCatalog
from ..roles.executor import RoleExecutor
from .mailbox import Mailbox
from .models import ApprovalStatus, Step, StepStatus, WorkflowStatus
from .workspace import Workspace


class WorkflowEngine:
    """Manages workflow lifecycle: create -> plan -> execute -> gate -> complete.

    Every state transition writes to SQLite BEFORE execution (crash recovery).
    Steps with depends_on are scheduled via DAG: independent steps run concurrently.
    """

    def __init__(
        self,
        db: Database,
        events: EventBus,
        role_executor: RoleExecutor,
        roles: RoleCatalog,
        gates: dict[str, Gate] | None = None,
        max_retries: int = 3,
        max_concurrent: int = 2,
        mailbox: Mailbox | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._db = db
        self._events = events
        self._role_executor = role_executor
        self._roles = roles
        self._gates = gates or {}
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, tuple[bool, str]] = {}
        self._mailbox = mailbox
        self._base_dir = base_dir
        self._workspaces: dict[str, Workspace] = {}

    async def create_workflow(self, task: str, steps: list[Step]) -> str:
        """Create a workflow with pre-planned steps. Returns workflow ID."""
        workflow_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        # Write workflow to DB
        await self._db.conn.execute(
            "INSERT INTO workflows (id, status, input, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (workflow_id, WorkflowStatus.CREATED.value, task, now, now),
        )

        # Write steps to DB
        for i, step in enumerate(steps):
            step.id = uuid.uuid4().hex[:12]
            step.workflow_id = workflow_id
            step.ordinal = i
            await self._db.conn.execute(
                "INSERT INTO steps "
                "(id, workflow_id, ordinal, role_id, instructions, status, depends_on) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (step.id, workflow_id, i, step.role_id, step.instructions,
                 StepStatus.PENDING.value, json.dumps(step.depends_on)),
            )

        await self._db.conn.commit()

        # Create per-workflow workspace if base_dir is configured
        if self._base_dir:
            self._workspaces[workflow_id] = Workspace(
                workflow_id, self._base_dir, self._events
            )

        await self._events.emit(Event(
            type=WORKFLOW_CREATED,
            data={"workflow_id": workflow_id, "task": task, "step_count": len(steps)},
        ))
        return workflow_id

    async def execute_workflow(self, workflow_id: str) -> None:
        """Execute all steps in a workflow, respecting DAG dependencies."""
        await self._update_workflow_status(workflow_id, WorkflowStatus.EXECUTING)
        await self._events.emit(Event(
            type=WORKFLOW_EXECUTING, data={"workflow_id": workflow_id}
        ))

        try:
            steps = await self._load_steps(workflow_id)
            await self._execute_dag(workflow_id, steps)

            # Check if all completed
            steps = await self._load_steps(workflow_id)
            all_done = all(s.status == StepStatus.COMPLETED for s in steps)

            if all_done:
                await self._update_workflow_status(workflow_id, WorkflowStatus.COMPLETED)
                total_cost = sum(s.cost_usd for s in steps)
                total_tokens = sum(s.tokens_used for s in steps)
                await self._db.conn.execute(
                    "UPDATE workflows SET total_cost_usd = ?, total_tokens = ? WHERE id = ?",
                    (total_cost, total_tokens, workflow_id),
                )
                await self._db.conn.commit()
                await self._events.emit(Event(
                    type=WORKFLOW_COMPLETED,
                    data={"workflow_id": workflow_id, "cost_usd": total_cost},
                ))
            else:
                failed = [s for s in steps if s.status == StepStatus.FAILED]
                if failed:
                    error = failed[0].error or "Step failed"
                    await self._update_workflow_status(
                        workflow_id, WorkflowStatus.FAILED, error=error
                    )
                    await self._events.emit(Event(
                        type=WORKFLOW_FAILED,
                        data={"workflow_id": workflow_id, "error": error},
                    ))
        except Exception as e:
            await self._update_workflow_status(
                workflow_id, WorkflowStatus.FAILED, error=str(e)
            )
            await self._events.emit(Event(
                type=WORKFLOW_FAILED,
                data={"workflow_id": workflow_id, "error": str(e)},
            ))

    async def _execute_dag(self, workflow_id: str, steps: list[Step]) -> None:
        """Execute steps respecting depends_on DAG ordering."""
        completed_ordinals: set[int] = {
            s.ordinal for s in steps if s.status == StepStatus.COMPLETED
        }
        pending = [s for s in steps if s.status == StepStatus.PENDING]

        while pending:
            # Find steps whose dependencies are all satisfied
            ready = [
                s for s in pending
                if all(dep in completed_ordinals for dep in s.depends_on)
            ]
            if not ready:
                # Deadlock or all waiting on approval
                break

            # Execute ready steps concurrently (bounded by semaphore)
            tasks = [self._execute_step_with_retry(workflow_id, s) for s in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready, results):
                if isinstance(result, Exception):
                    # Step failed
                    pass
                elif result is True:
                    completed_ordinals.add(step.ordinal)

            # Reload pending steps
            steps = await self._load_steps(workflow_id)
            pending = [s for s in steps if s.status == StepStatus.PENDING]

    async def _execute_step_with_retry(self, workflow_id: str, step: Step) -> bool:
        """Execute a step with retry logic. Returns True if completed."""
        async with self._semaphore:
            failed_results: list[tuple[int, Any]] = []
            for attempt in range(self._max_retries):
                success, result = await self._execute_step(workflow_id, step)
                if success:
                    # If this was a retry that succeeded, store the lesson
                    if failed_results and result is not None:
                        last_fail_attempt, last_fail_result = failed_results[-1]
                        try:
                            await self._role_executor.store_retry_lesson(
                                role_id=step.role_id,
                                instructions=step.instructions,
                                failed_result=last_fail_result,
                                success_result=result,
                                attempt=last_fail_attempt,
                            )
                        except Exception:
                            pass
                    return True

                # Track failure for retry lessons
                if result is not None:
                    failed_results.append((attempt, result))

                # Check if we should retry or it's a permanent failure
                step = await self._load_step(step.id)
                if step.status == StepStatus.FAILED:
                    if attempt < self._max_retries - 1:
                        # Reset for retry
                        await self._update_step_status(step.id, StepStatus.PENDING)
                    else:
                        return False
            return False

    async def _execute_step(self, workflow_id: str, step: Step) -> tuple[bool, Any]:
        """Execute a single step. Returns (success, result)."""
        now = datetime.now(timezone.utc).isoformat()

        # Mark as running BEFORE execution
        await self._db.conn.execute(
            "UPDATE steps SET status = ?, started_at = ? WHERE id = ?",
            (StepStatus.RUNNING.value, now, step.id),
        )
        await self._db.conn.commit()
        await self._events.emit(Event(
            type=STEP_STARTED,
            data={"workflow_id": workflow_id, "step_id": step.id, "role_id": step.role_id},
        ))

        # Set up built-in tool router for this step
        from ..tools.executor import ToolExecutor

        tool_executor = getattr(self._role_executor, "tool_executor", None)
        has_builtin_setup = isinstance(tool_executor, ToolExecutor) and self._mailbox
        if has_builtin_setup:
            from ..tools.builtin import BuiltinToolRouter

            router = BuiltinToolRouter(
                workflow_id=workflow_id,
                step_id=step.id,
                mailbox=self._mailbox,
                memory=getattr(self._role_executor, "memory", None),
                workspace=self._workspaces.get(workflow_id),
            )
            tool_executor.set_builtin_router(router)

        try:
            # Build context with previous outputs
            context = await self._build_step_context(workflow_id, step)

            # Fetch mailbox messages for this step
            messages: list[dict[str, str]] | None = None
            if self._mailbox and step.id:
                try:
                    inbox = await self._mailbox.receive(workflow_id, step.id)
                    if inbox:
                        messages = [
                            {"from": m.from_step, "body": m.body}
                            for m in inbox
                        ]
                except Exception:
                    pass

            # Execute via RoleExecutor (don't store memory yet — we'll store with outcome)
            result = await self._role_executor.execute(
                role_id=step.role_id,
                instructions=step.instructions,
                context=context,
                messages=messages,
                store_memory=False,
            )

            # Write output BEFORE gate checking
            await self._db.conn.execute(
                "UPDATE steps SET output_data = ?, cost_usd = ?, tokens_used = ? WHERE id = ?",
                (json.dumps(result.output), result.cost_usd, result.tokens_used, step.id),
            )
            await self._db.conn.commit()

            await self._events.emit(Event(
                type=COST_UPDATED,
                data={"workflow_id": workflow_id, "step_id": step.id, "cost_usd": result.cost_usd},
            ))

            # Run gates
            gate_passed, gate_results = await self._check_gates(
                workflow_id, step, result.output
            )

            # Store outcome with enriched metadata
            quality_score = 0
            if isinstance(result.output, dict):
                quality_score = result.output.get("quality_score", 0)
            try:
                await self._role_executor.store_execution_outcome(
                    role_id=step.role_id,
                    instructions=step.instructions,
                    result=result,
                    success=gate_passed,
                    quality_score=quality_score,
                    gate_results=gate_results,
                )
            except Exception:
                pass

            if not gate_passed:
                return False, result

            # Mark completed
            completed_at = datetime.now(timezone.utc).isoformat()
            await self._db.conn.execute(
                "UPDATE steps SET status = ?, completed_at = ? WHERE id = ?",
                (StepStatus.COMPLETED.value, completed_at, step.id),
            )
            await self._db.conn.commit()
            await self._events.emit(Event(
                type=STEP_COMPLETED,
                data={"workflow_id": workflow_id, "step_id": step.id},
            ))
            return True, result

        except Exception as e:
            await self._db.conn.execute(
                "UPDATE steps SET status = ?, error = ? WHERE id = ?",
                (StepStatus.FAILED.value, str(e), step.id),
            )
            await self._db.conn.commit()
            await self._events.emit(Event(
                type=STEP_FAILED,
                data={"workflow_id": workflow_id, "step_id": step.id, "error": str(e)},
            ))
            return False, None
        finally:
            # Clean up built-in router
            if has_builtin_setup:
                tool_executor.clear_builtin_router()

    async def _check_gates(
        self, workflow_id: str, step: Step, output: dict[str, Any]
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Check all gates for a step's role. Returns (passed, gate_results)."""
        gate_results: list[dict[str, Any]] = []
        try:
            role = self._roles.get(step.role_id)
        except KeyError:
            return True, gate_results

        for gate_config in role.gates:
            gate = self._gates.get(gate_config.type)
            if not gate:
                continue

            context: dict[str, Any] = {}
            if gate_config.threshold is not None:
                context["threshold"] = gate_config.threshold
            if gate_config.command is not None:
                context["command"] = gate_config.command

            result = await gate.check(output, context)
            gate_results.append({
                "gate": gate_config.type,
                "passed": result.passed,
                "message": result.message,
            })

            if not result.passed:
                if result.details and result.details.get("requires_approval"):
                    # Approval gate — pause workflow
                    await self._request_approval(workflow_id, step)
                    return False, gate_results
                else:
                    # Quality/test gate — mark failed for retry
                    await self._db.conn.execute(
                        "UPDATE steps SET status = ?, error = ? WHERE id = ?",
                        (StepStatus.FAILED.value, result.message, step.id),
                    )
                    await self._db.conn.commit()
                    return False, gate_results

        return True, gate_results

    async def _request_approval(self, workflow_id: str, step: Step) -> None:
        """Create an approval record and pause the workflow."""
        approval_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        await self._db.conn.execute(
            "INSERT INTO approvals (id, workflow_id, step_id, type, prompt, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (approval_id, workflow_id, step.id, "approval",
             f"Approval required for step {step.ordinal} ({step.role_id})",
             ApprovalStatus.PENDING.value, now),
        )
        await self._update_workflow_status(workflow_id, WorkflowStatus.WAITING_APPROVAL)
        await self._db.conn.commit()

        self._approval_events[approval_id] = asyncio.Event()
        await self._events.emit(Event(
            type=APPROVAL_REQUESTED,
            data={"workflow_id": workflow_id, "approval_id": approval_id, "step_id": step.id},
        ))

    async def resolve_approval(self, approval_id: str, approved: bool, reason: str = "") -> None:
        """Resolve a pending approval."""
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        now = datetime.now(timezone.utc).isoformat()

        await self._db.conn.execute(
            "UPDATE approvals SET status = ?, response = ?, resolved_at = ? WHERE id = ?",
            (status.value, reason, now, approval_id),
        )
        await self._db.conn.commit()

        self._approval_results[approval_id] = (approved, reason)
        event = self._approval_events.get(approval_id)
        if event:
            event.set()

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Load a workflow and its steps from the DB."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Workflow '{workflow_id}' not found")

        steps = await self._load_steps(workflow_id)
        return {
            "id": row["id"],
            "status": row["status"],
            "input": row["input"],
            "current_step": row["current_step"],
            "total_cost_usd": row["total_cost_usd"],
            "total_tokens": row["total_tokens"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "steps": [
                {
                    "id": s.id,
                    "ordinal": s.ordinal,
                    "role_id": s.role_id,
                    "instructions": s.instructions,
                    "status": s.status.value,
                    "cost_usd": s.cost_usd,
                    "tokens_used": s.tokens_used,
                    "error": s.error,
                    "depends_on": s.depends_on,
                }
                for s in steps
            ],
        }

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows (summary)."""
        cursor = await self._db.conn.execute(
            "SELECT id, status, input, total_cost_usd, total_tokens, created_at "
            "FROM workflows ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "status": r["status"],
                "input": r["input"],
                "total_cost_usd": r["total_cost_usd"],
                "total_tokens": r["total_tokens"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    async def _build_step_context(
        self, workflow_id: str, step: Step
    ) -> dict[str, Any]:
        """Build execution context with outputs from dependency steps."""
        if not step.depends_on:
            return {}

        steps = await self._load_steps(workflow_id)
        dep_outputs = []
        for dep_ordinal in step.depends_on:
            dep_step = next((s for s in steps if s.ordinal == dep_ordinal), None)
            if dep_step and dep_step.output_data:
                dep_outputs.append(dep_step.output_data)

        return {"previous_outputs": dep_outputs} if dep_outputs else {}

    async def _load_steps(self, workflow_id: str) -> list[Step]:
        """Load all steps for a workflow from DB."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM steps WHERE workflow_id = ? ORDER BY ordinal",
            (workflow_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_step(row) for row in rows]

    async def _load_step(self, step_id: str) -> Step:
        cursor = await self._db.conn.execute(
            "SELECT * FROM steps WHERE id = ?", (step_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Step '{step_id}' not found")
        return self._row_to_step(row)

    @staticmethod
    def _row_to_step(row: Any) -> Step:
        depends_on = json.loads(row["depends_on"]) if row["depends_on"] else []
        output_data = json.loads(row["output_data"]) if row["output_data"] else {}
        return Step(
            id=row["id"],
            workflow_id=row["workflow_id"],
            ordinal=row["ordinal"],
            role_id=row["role_id"],
            instructions=row["instructions"],
            status=StepStatus(row["status"]),
            output_data=output_data,
            cost_usd=row["cost_usd"],
            tokens_used=row["tokens_used"],
            error=row["error"],
            depends_on=depends_on,
        )

    async def _update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, error: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            "UPDATE workflows SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status.value, error, now, workflow_id),
        )
        await self._db.conn.commit()

    async def _update_step_status(self, step_id: str, status: StepStatus) -> None:
        await self._db.conn.execute(
            "UPDATE steps SET status = ?, error = NULL WHERE id = ?",
            (status.value, step_id),
        )
        await self._db.conn.commit()
