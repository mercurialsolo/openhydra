"""Tests for gate implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from openhydra.gates.approval import ApprovalGate
from openhydra.gates.quality import QualityGate
from openhydra.gates.tests_gate import TestsGate


class TestQualityGate:
    async def test_passes_above_threshold(self) -> None:
        gate = QualityGate()
        result = await gate.check({"quality_score": 30}, {"threshold": 24})
        assert result.passed is True
        assert "30/24" in result.message

    async def test_fails_below_threshold(self) -> None:
        gate = QualityGate()
        result = await gate.check({"quality_score": 20}, {"threshold": 24})
        assert result.passed is False

    async def test_passes_at_threshold(self) -> None:
        gate = QualityGate()
        result = await gate.check({"quality_score": 24}, {"threshold": 24})
        assert result.passed is True

    async def test_missing_score(self) -> None:
        gate = QualityGate()
        result = await gate.check({}, {"threshold": 24})
        assert result.passed is False

    async def test_default_threshold(self) -> None:
        gate = QualityGate()
        result = await gate.check({"quality_score": 24}, {})
        assert result.passed is True

    async def test_name(self) -> None:
        assert QualityGate().name == "quality"


class TestApprovalGate:
    async def test_always_fails_with_approval_required(self) -> None:
        gate = ApprovalGate()
        result = await gate.check({"quality_score": 100}, {})
        assert result.passed is False
        assert result.details["requires_approval"] is True

    async def test_name(self) -> None:
        assert ApprovalGate().name == "approval"


class TestTestsGate:
    async def test_passes_on_success(self) -> None:
        gate = TestsGate()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"All tests passed", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await gate.check({}, {"command": "echo ok"})

        assert result.passed is True
        assert result.details["exit_code"] == 0

    async def test_fails_on_nonzero_exit(self) -> None:
        gate = TestsGate()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"FAILED", b""))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await gate.check({}, {"command": "false"})

        assert result.passed is False
        assert result.details["exit_code"] == 1

    async def test_name(self) -> None:
        assert TestsGate().name == "tests_pass"
