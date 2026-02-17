"""Skill security pipeline — orchestrates static analysis, sandbox, and LLM review."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from openhydra.events import (
    SKILL_APPROVAL_NEEDED,
    SKILL_APPROVED,
    SKILL_REJECTED,
    SKILL_REVIEW_STARTED,
    Event,
    EventBus,
)

from .llm_reviewer import LlmReviewer
from .models import RiskLevel, ScanResult, SkillApprovalStatus
from .sandbox import SandboxExecutor
from .static_analyzer import StaticAnalyzer

if TYPE_CHECKING:
    from pathlib import Path

    from openhydra.agents.registry import AgentRegistry
    from openhydra.db import Database

logger = logging.getLogger(__name__)


class SkillSecurityPipeline:
    """Orchestrates all security scanning stages and manages approval state."""

    def __init__(
        self,
        db: Database,
        events: EventBus,
        agents: AgentRegistry,
        *,
        auto_approve_risk: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._db = db
        self._events = events
        self._agents = agents
        self.auto_approve_risk = auto_approve_risk
        self._static = StaticAnalyzer()
        self._sandbox = SandboxExecutor()

    async def submit_for_review(
        self, skill_id: str, source_path: str, *, is_bundled: bool = False,
    ) -> SkillApprovalStatus:
        """Register a skill for review. Bundled skills are auto-approved immediately."""
        if is_bundled:
            await self._set_status(skill_id, SkillApprovalStatus.APPROVED, source_path)
            return SkillApprovalStatus.APPROVED

        await self._set_status(skill_id, SkillApprovalStatus.PENDING_REVIEW, source_path)
        return SkillApprovalStatus.PENDING_REVIEW

    async def run_scan(self, skill_id: str, skill_dir: Path) -> ScanResult:
        """Run the full 3-stage security scan.

        Returns ScanResult with aggregate risk level. Updates DB status based
        on results and auto_approve_risk threshold.
        """
        await self._set_status(skill_id, SkillApprovalStatus.SCANNING)
        await self._events.emit(Event(
            type=SKILL_REVIEW_STARTED,
            data={"skill_id": skill_id, "path": str(skill_dir)},
        ))

        scan = ScanResult(skill_id=skill_id)

        # Stage 1: Static analysis
        scan.static_findings = self._static.scan_skill_dir(skill_dir)
        static_max = max(
            (f.severity for f in scan.static_findings), default=RiskLevel.SAFE,
        )
        scan.risk_level = static_max

        # Short-circuit if critical findings
        if static_max >= RiskLevel.CRITICAL:
            await self._store_scan(skill_id, scan)
            await self._set_status(skill_id, SkillApprovalStatus.AWAITING_APPROVAL)
            await self._emit_approval_needed(skill_id, scan)
            return scan

        # Stage 2: Sandbox execution
        scan.sandbox_results = await self._sandbox.execute_all(skill_dir)
        for result in scan.sandbox_results:
            if result.timed_out or result.exit_code != 0:
                scan.risk_level = max(scan.risk_level, RiskLevel.MEDIUM, key=_risk_order)

        # Stage 3: LLM review
        reviewer = LlmReviewer(self._agents)
        skill_content = self._read_skill_content(skill_dir)
        scan.llm_review = await reviewer.review(skill_id, skill_content)
        scan.risk_level = max(scan.risk_level, scan.llm_review.risk_level, key=_risk_order)

        # Decision
        if scan.risk_level <= self.auto_approve_risk:
            scan.auto_approved = True
            await self._store_scan(skill_id, scan)
            await self._set_status(skill_id, SkillApprovalStatus.APPROVED)
            await self._events.emit(Event(
                type=SKILL_APPROVED,
                data={"skill_id": skill_id, "auto": True, "risk_level": scan.risk_level.value},
            ))
        else:
            await self._store_scan(skill_id, scan)
            await self._set_status(skill_id, SkillApprovalStatus.AWAITING_APPROVAL)
            await self._emit_approval_needed(skill_id, scan)

        return scan

    async def approve_skill(self, skill_id: str, approved_by: str = "user") -> bool:
        """Manually approve a skill."""
        row = await self._get_approval(skill_id)
        if not row:
            return False
        status = row["status"]
        if status not in (
            SkillApprovalStatus.AWAITING_APPROVAL.value,
            SkillApprovalStatus.PENDING_REVIEW.value,
        ):
            return False

        await self._db.conn.execute(
            "UPDATE skill_approvals SET status = ?, approved_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE skill_id = ?",
            (SkillApprovalStatus.APPROVED.value, approved_by, skill_id),
        )
        await self._db.conn.commit()
        await self._events.emit(Event(
            type=SKILL_APPROVED,
            data={"skill_id": skill_id, "approved_by": approved_by, "auto": False},
        ))
        return True

    async def reject_skill(self, skill_id: str, rejected_by: str = "user") -> bool:
        """Manually reject a skill."""
        row = await self._get_approval(skill_id)
        if not row:
            return False
        status = row["status"]
        if status not in (
            SkillApprovalStatus.AWAITING_APPROVAL.value,
            SkillApprovalStatus.PENDING_REVIEW.value,
        ):
            return False

        await self._db.conn.execute(
            "UPDATE skill_approvals SET status = ?, approved_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE skill_id = ?",
            (SkillApprovalStatus.REJECTED.value, rejected_by, skill_id),
        )
        await self._db.conn.commit()
        await self._events.emit(Event(
            type=SKILL_REJECTED,
            data={"skill_id": skill_id, "rejected_by": rejected_by},
        ))
        return True

    async def get_status(self, skill_id: str) -> SkillApprovalStatus | None:
        """Get the current approval status of a skill."""
        row = await self._get_approval(skill_id)
        if not row:
            return None
        return SkillApprovalStatus(row["status"])

    async def list_pending(self) -> list[dict]:
        """List all skills awaiting approval."""
        cursor = await self._db.conn.execute(
            "SELECT skill_id, status, source_path, scan_result_json, created_at "
            "FROM skill_approvals WHERE status IN (?, ?)",
            (SkillApprovalStatus.AWAITING_APPROVAL.value, SkillApprovalStatus.PENDING_REVIEW.value),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -- Internal helpers --

    async def _set_status(
        self, skill_id: str, status: SkillApprovalStatus, source_path: str = "",
    ) -> None:
        await self._db.conn.execute(
            "INSERT INTO skill_approvals (skill_id, status, source_path) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(skill_id) DO UPDATE SET status = ?, updated_at = CURRENT_TIMESTAMP",
            (skill_id, status.value, source_path, status.value),
        )
        await self._db.conn.commit()

    async def _store_scan(self, skill_id: str, scan: ScanResult) -> None:
        scan_json = json.dumps(asdict(scan), default=str)
        await self._db.conn.execute(
            "UPDATE skill_approvals SET scan_result_json = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE skill_id = ?",
            (scan_json, skill_id),
        )
        await self._db.conn.commit()

    async def _get_approval(self, skill_id: str) -> dict | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM skill_approvals WHERE skill_id = ?", (skill_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def _emit_approval_needed(self, skill_id: str, scan: ScanResult) -> None:
        findings_summary = [f.description for f in scan.static_findings[:5]]
        await self._events.emit(Event(
            type=SKILL_APPROVAL_NEEDED,
            data={
                "skill_id": skill_id,
                "risk_level": scan.risk_level.value,
                "findings": findings_summary,
            },
        ))

    def _read_skill_content(self, skill_dir: Path) -> str:
        """Read SKILL.md content for LLM review."""
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(errors="replace")[:8192]
        return ""


def _risk_order(level: RiskLevel) -> int:
    """Return numeric order for RiskLevel comparison."""
    return list(RiskLevel).index(level)
