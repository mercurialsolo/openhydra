"""Memory store protocol and entry types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass
class MemoryEntry:
    """A single memory entry with optional similarity score."""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # similarity score (0-1), set by search
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for pluggable vector-searchable memory backends."""

    async def store(
        self,
        collection: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Store a memory entry. Returns the entry ID."""
        ...

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Search for relevant memories by semantic similarity."""
        ...

    async def get(self, collection: str, entry_id: str) -> MemoryEntry | None:
        """Get a specific memory entry by ID."""
        ...

    async def delete(self, collection: str, entry_id: str) -> bool:
        """Delete a memory entry. Returns True if found and deleted."""
        ...

    async def list_collections(self) -> list[str]:
        """List all known collections."""
        ...
