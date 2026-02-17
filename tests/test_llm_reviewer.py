"""Tests for the LLM-based skill security reviewer."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from openhydra.skills.security.llm_reviewer import LlmReviewer
from openhydra.skills.security.models import RiskLevel


@dataclass
class _FakeResponse:
    result: str


def _make_registry(response_text: str | None = None, error: Exception | None = None):
    """Create a mock AgentRegistry with a fake default provider."""
    registry = MagicMock()
    provider = MagicMock()

    if error:
        provider.run = AsyncMock(side_effect=error)
    elif response_text is not None:
        provider.run = AsyncMock(return_value=_FakeResponse(result=response_text))
    else:
        provider.run = AsyncMock(return_value=_FakeResponse(result="{}"))

    registry.default.return_value = provider
    return registry


class TestLlmReviewer:
    """Test LLM reviewer response parsing and error handling."""

    @pytest.mark.asyncio()
    async def test_parses_json_response(self) -> None:
        response = '{"risk_level": "low", "findings": ["minor issue"], "recommendation": "approve"}'
        registry = _make_registry(response)
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "some content")

        assert result.risk_level == RiskLevel.LOW
        assert result.findings == ["minor issue"]
        assert result.recommendation == "approve"

    @pytest.mark.asyncio()
    async def test_parses_markdown_wrapped_json(self) -> None:
        response = (
            '```json\n{"risk_level": "safe", "findings": [],'
            ' "recommendation": "approve"}\n```'
        )
        registry = _make_registry(response)
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "safe content")

        assert result.risk_level == RiskLevel.SAFE
        assert result.findings == []

    @pytest.mark.asyncio()
    async def test_parses_markdown_fences_no_lang(self) -> None:
        response = (
            '```\n{"risk_level": "high", "findings": ["bad stuff"],'
            ' "recommendation": "reject"}\n```'
        )
        registry = _make_registry(response)
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "dangerous content")

        assert result.risk_level == RiskLevel.HIGH
        assert "bad stuff" in result.findings

    @pytest.mark.asyncio()
    async def test_handles_provider_failure(self) -> None:
        registry = _make_registry(error=RuntimeError("connection failed"))
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "content")

        assert result.risk_level == RiskLevel.MEDIUM
        assert any("failed" in f.lower() for f in result.findings)

    @pytest.mark.asyncio()
    async def test_handles_no_provider(self) -> None:
        registry = MagicMock()
        registry.default.side_effect = RuntimeError("No agent providers registered")
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "content")

        assert result.risk_level == RiskLevel.MEDIUM
        assert any("no agent" in f.lower() for f in result.findings)

    @pytest.mark.asyncio()
    async def test_handles_invalid_json(self) -> None:
        registry = _make_registry("this is not json at all")
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "content")

        assert result.risk_level == RiskLevel.MEDIUM
        assert any("parse" in f.lower() for f in result.findings)

    @pytest.mark.asyncio()
    async def test_handles_unknown_risk_level(self) -> None:
        response = '{"risk_level": "unknown_level", "findings": [], "recommendation": "review"}'
        registry = _make_registry(response)
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "content")

        # Should default to MEDIUM for unknown risk levels
        assert result.risk_level == RiskLevel.MEDIUM

    @pytest.mark.asyncio()
    async def test_critical_risk_parsed(self) -> None:
        response = (
            '{"risk_level": "critical", "findings": ["RCE possible"],'
            ' "recommendation": "reject"}'
        )
        registry = _make_registry(response)
        reviewer = LlmReviewer(registry)

        result = await reviewer.review("test-skill", "evil content")

        assert result.risk_level == RiskLevel.CRITICAL
        assert result.recommendation == "reject"
