"""Data models for skill security scanning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SkillApprovalStatus(str, Enum):
    """Status of a skill in the approval pipeline."""

    PENDING_REVIEW = "pending_review"
    SCANNING = "scanning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    """Risk level assessed by the scanning pipeline."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __le__(self, other: RiskLevel) -> bool:
        order = list(RiskLevel)
        return order.index(self) <= order.index(other)

    def __lt__(self, other: RiskLevel) -> bool:
        order = list(RiskLevel)
        return order.index(self) < order.index(other)

    def __ge__(self, other: RiskLevel) -> bool:
        order = list(RiskLevel)
        return order.index(self) >= order.index(other)

    def __gt__(self, other: RiskLevel) -> bool:
        order = list(RiskLevel)
        return order.index(self) > order.index(other)


@dataclass
class StaticFinding:
    """A finding from static analysis."""

    pattern: str
    description: str
    file_path: str
    line_number: int
    severity: RiskLevel
    matched_text: str = ""


@dataclass
class SandboxResult:
    """Result of running a script in a sandbox."""

    script_path: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_seconds: float = 0.0


@dataclass
class LlmReviewResult:
    """Result of an LLM security review."""

    risk_level: RiskLevel = RiskLevel.SAFE
    findings: list[str] = field(default_factory=list)
    recommendation: str = ""
    raw_response: str = ""


@dataclass
class ScanResult:
    """Aggregate result from the full scanning pipeline."""

    skill_id: str
    risk_level: RiskLevel = RiskLevel.SAFE
    static_findings: list[StaticFinding] = field(default_factory=list)
    sandbox_results: list[SandboxResult] = field(default_factory=list)
    llm_review: LlmReviewResult | None = None
    auto_approved: bool = False
    error: str = ""
