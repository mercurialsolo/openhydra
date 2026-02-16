"""Memory compaction — age pruning, size capping, deduplication, TF-IDF rebuild."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .base import MemoryStore
from .embeddings import TfidfEmbeddingProvider


@dataclass
class CompactionConfig:
    """Tuning knobs for memory compaction."""

    max_entries_per_collection: int = 500
    max_age_days: int = 90
    similarity_threshold: float = 0.92
    compact_after_stores: int = 50


class MemoryCompactor:
    """Compacts a memory collection by pruning old, excess, and duplicate entries."""

    def __init__(
        self,
        store: MemoryStore,
        embedding_provider: TfidfEmbeddingProvider | None = None,
        config: CompactionConfig | None = None,
    ) -> None:
        self._store = store
        self._embedding_provider = embedding_provider
        self._config = config or CompactionConfig()

    async def compact(self, collection: str) -> int:
        """Run full compaction on a collection. Returns number of entries removed."""
        removed = 0
        removed += await self._prune_old(collection)
        removed += await self._cap_size(collection)
        removed += await self._deduplicate(collection)
        await self._rebuild_tfidf(collection)
        return removed

    async def maybe_compact(self, collection: str, store_count: int) -> int:
        """Trigger compaction if store_count hits the interval threshold."""
        if store_count > 0 and store_count % self._config.compact_after_stores == 0:
            return await self.compact(collection)
        return 0

    async def _prune_old(self, collection: str) -> int:
        """Delete entries older than max_age_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._config.max_age_days)
        entries = await self._store.list_entries(
            collection, limit=10000, oldest_first=True
        )
        removed = 0
        for entry in entries:
            if entry.created_at.replace(tzinfo=timezone.utc) < cutoff:
                if await self._store.delete(collection, entry.id):
                    removed += 1
            else:
                break  # entries are sorted oldest first
        return removed

    async def _cap_size(self, collection: str) -> int:
        """If collection exceeds max_entries, remove oldest excess."""
        count = await self._store.count(collection)
        if count <= self._config.max_entries_per_collection:
            return 0

        excess = count - self._config.max_entries_per_collection
        oldest = await self._store.list_entries(
            collection, limit=excess, oldest_first=True
        )
        removed = 0
        for entry in oldest:
            if await self._store.delete(collection, entry.id):
                removed += 1
        return removed

    async def _deduplicate(self, collection: str) -> int:
        """Remove near-duplicate entries (cosine similarity > threshold)."""
        if not self._embedding_provider:
            return 0

        entries = await self._store.list_entries(
            collection, limit=10000, oldest_first=True
        )
        if len(entries) < 2:
            return 0

        # Embed all entries
        texts = [e.content for e in entries]
        embeddings = await self._embedding_provider.embed(texts)

        # Mark duplicates (keep the newer one)
        to_remove: set[str] = set()
        for i in range(len(entries)):
            if entries[i].id in to_remove:
                continue
            for j in range(i + 1, len(entries)):
                if entries[j].id in to_remove:
                    continue
                sim = self._cosine_similarity(embeddings[i], embeddings[j])
                if sim >= self._config.similarity_threshold:
                    # Remove the older entry (i is older since oldest_first=True)
                    to_remove.add(entries[i].id)
                    break

        removed = 0
        for entry_id in to_remove:
            if await self._store.delete(collection, entry_id):
                removed += 1
        return removed

    async def _rebuild_tfidf(self, collection: str) -> None:
        """Refit TF-IDF vectorizer from remaining entries."""
        if not self._embedding_provider:
            return

        entries = await self._store.list_entries(
            collection, limit=10000, oldest_first=False
        )
        texts = [e.content for e in entries]
        self._embedding_provider.rebuild_corpus(texts)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
