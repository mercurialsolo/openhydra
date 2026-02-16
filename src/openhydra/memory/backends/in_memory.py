"""In-memory memory store for testing."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from ..base import EmbeddingProvider, MemoryEntry


class InMemoryStore:
    """Dict-based memory store. No persistence — for testing only."""

    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider
        # collection -> id -> (entry, embedding)
        self._data: dict[str, dict[str, tuple[MemoryEntry, list[float]]]] = {}

    async def store(
        self,
        collection: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        entry_id = uuid.uuid4().hex[:12]
        if embedding is None:
            embeddings = await self._embedding_provider.embed([content])
            embedding = embeddings[0]

        entry = MemoryEntry(
            id=entry_id,
            content=content,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        if collection not in self._data:
            self._data[collection] = {}
        self._data[collection][entry_id] = (entry, embedding)
        return entry_id

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        if collection not in self._data:
            return []

        query_embedding = (await self._embedding_provider.embed([query]))[0]
        scored: list[tuple[float, MemoryEntry]] = []

        for entry, embedding in self._data[collection].values():
            if filters and not self._matches_filters(entry.metadata, filters):
                continue
            score = self._cosine_similarity(query_embedding, embedding)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, entry in scored[:limit]:
            entry.score = score
            results.append(entry)
        return results

    async def get(self, collection: str, entry_id: str) -> MemoryEntry | None:
        coll = self._data.get(collection, {})
        pair = coll.get(entry_id)
        return pair[0] if pair else None

    async def delete(self, collection: str, entry_id: str) -> bool:
        coll = self._data.get(collection, {})
        if entry_id in coll:
            del coll[entry_id]
            return True
        return False

    async def list_collections(self) -> list[str]:
        return list(self._data.keys())

    async def count(self, collection: str) -> int:
        return len(self._data.get(collection, {}))

    async def list_entries(
        self,
        collection: str,
        limit: int = 100,
        oldest_first: bool = True,
    ) -> list[MemoryEntry]:
        coll = self._data.get(collection, {})
        entries = [entry for entry, _ in coll.values()]
        entries.sort(key=lambda e: e.created_at, reverse=not oldest_first)
        return entries[:limit]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if metadata.get(key) != value:
                return False
        return True
