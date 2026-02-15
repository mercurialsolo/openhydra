"""Agent provider protocol and session result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolDefinition:
    """A tool available to an agent during a session."""

    name: str
    description: str
    input_schema: dict[str, Any] | None = None


@dataclass
class ArtifactRef:
    """Reference to a file created or modified during a session."""

    path: str
    hash: str | None = None
    size_bytes: int | None = None


@dataclass
class SessionResult:
    """Result from an agent session."""

    output: dict[str, Any]  # structured output (validated against schema)
    raw_text: str  # full text response
    artifacts: list[ArtifactRef] = field(default_factory=list)
    tokens_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    model: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@runtime_checkable
class AgentProvider(Protocol):
    """Protocol for pluggable agent session providers."""

    @property
    def name(self) -> str:
        """Unique provider identifier."""
        ...

    async def run_session(
        self,
        instructions: str,
        system_prompt: str,
        tools: list[ToolDefinition] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 100_000,
        model: str | None = None,
    ) -> SessionResult:
        """Run a single agent session and return structured output."""
        ...

    async def check_availability(self) -> bool:
        """Return True if this provider is configured and reachable."""
        ...
