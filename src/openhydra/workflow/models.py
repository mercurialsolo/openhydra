"""Workflow, step, and approval data models."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class WorkflowStatus(str, enum.Enum):
    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROVIDED = "provided"  # human provided requested input


class ApprovalType(str, enum.Enum):
    APPROVAL = "approval"
    CORRECTION = "correction"
    INPUT = "input"
    DECISION = "decision"


@dataclass
class Step:
    """A single step in a workflow plan."""

    id: str = ""
    workflow_id: str = ""
    ordinal: int = 0
    role_id: str = ""
    instructions: str = ""
    status: StepStatus = StepStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_used: int = 0
    error: str | None = None
    depends_on: list[int] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class Approval:
    """A pending human interaction request."""

    id: str = ""
    workflow_id: str = ""
    step_id: str = ""
    type: ApprovalType = ApprovalType.APPROVAL
    prompt: str = ""
    response: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


@dataclass
class Workflow:
    """A multi-step workflow."""

    id: str = ""
    status: WorkflowStatus = WorkflowStatus.CREATED
    input: str = ""  # original task description
    plan: list[Step] = field(default_factory=list)
    current_step: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
