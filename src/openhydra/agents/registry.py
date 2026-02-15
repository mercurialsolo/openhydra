"""Agent provider registry."""

from __future__ import annotations

from .base import AgentProvider


class AgentRegistry:
    """Registry of available agent providers."""

    def __init__(self) -> None:
        self._providers: dict[str, AgentProvider] = {}
        self._default: str | None = None

    def register(self, provider: AgentProvider, *, default: bool = False) -> None:
        """Register an agent provider."""
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name

    def get(self, name: str) -> AgentProvider:
        """Get a provider by name."""
        if name not in self._providers:
            available = ", ".join(self._providers.keys()) or "(none)"
            raise KeyError(f"Agent provider '{name}' not found. Available: {available}")
        return self._providers[name]

    def default(self) -> AgentProvider:
        """Get the default provider."""
        if self._default is None:
            raise RuntimeError("No agent providers registered")
        return self._providers[self._default]

    def set_default(self, name: str) -> None:
        """Set the default provider by name."""
        if name not in self._providers:
            raise KeyError(f"Agent provider '{name}' not registered")
        self._default = name

    def list_available(self) -> list[str]:
        """List names of all registered providers."""
        return list(self._providers.keys())
