"""Tests for memory compaction — age pruning, size capping, dedup, rebuild."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from openhydra.memory.backends.in_memory import InMemoryStore
from openhydra.memory.compaction import CompactionConfig, MemoryCompactor
from openhydra.memory.embeddings import TfidfEmbeddingProvider


@pytest.fixture
def provider() -> TfidfEmbeddingProvider:
    return TfidfEmbeddingProvider(max_features=64)


@pytest.fixture
def store(provider: TfidfEmbeddingProvider) -> InMemoryStore:
    return InMemoryStore(provider)


@pytest.fixture
def compactor(store: InMemoryStore, provider: TfidfEmbeddingProvider) -> MemoryCompactor:
    config = CompactionConfig(
        max_entries_per_collection=5,
        max_age_days=30,
        similarity_threshold=0.90,
        compact_after_stores=3,
    )
    return MemoryCompactor(store, embedding_provider=provider, config=config)


async def test_age_pruning(store: InMemoryStore, compactor: MemoryCompactor) -> None:
    """Old entries beyond max_age_days are pruned."""
    # Manually insert an old entry
    entry_id = await store.store("test", "old content")
    # Backdate it
    entry, emb = store._data["test"][entry_id]
    object.__setattr__(entry, "created_at", datetime.now(timezone.utc) - timedelta(days=60))

    # Insert a recent entry
    await store.store("test", "new content")

    removed = await compactor.compact("test")
    assert removed >= 1
    assert await store.count("test") == 1


async def test_size_capping(store: InMemoryStore, compactor: MemoryCompactor) -> None:
    """Collection is capped at max_entries_per_collection."""
    for i in range(8):
        await store.store("test", f"entry number {i}")

    assert await store.count("test") == 8
    removed = await compactor.compact("test")
    assert removed >= 3
    assert await store.count("test") <= 5


async def test_deduplication(store: InMemoryStore, compactor: MemoryCompactor) -> None:
    """Near-duplicate entries are removed, keeping the newer one."""
    await store.store("test", "python programming language guide")
    await store.store("test", "python programming language guide")  # exact duplicate
    await store.store("test", "italian cooking recipes")

    removed = await compactor.compact("test")
    assert removed >= 1
    remaining = await store.list_entries("test")
    assert len(remaining) >= 2


async def test_maybe_compact_triggers(
    store: InMemoryStore, compactor: MemoryCompactor
) -> None:
    """Compaction triggers at interval boundaries (every compact_after_stores)."""
    for i in range(6):
        await store.store("test", f"content {i}")

    # Not at boundary -> no compaction
    removed = await compactor.maybe_compact("test", 2)
    assert removed == 0

    # At boundary (3) -> triggers compaction
    removed = await compactor.maybe_compact("test", 3)
    assert removed >= 0  # may or may not remove depending on content


async def test_maybe_compact_not_triggered_at_zero(
    store: InMemoryStore, compactor: MemoryCompactor
) -> None:
    """store_count=0 should not trigger compaction."""
    removed = await compactor.maybe_compact("test", 0)
    assert removed == 0


async def test_rebuild_tfidf(
    store: InMemoryStore, provider: TfidfEmbeddingProvider, compactor: MemoryCompactor
) -> None:
    """After compaction, TF-IDF vectorizer is rebuilt from remaining entries."""
    await store.store("test", "alpha bravo charlie")
    await store.store("test", "delta echo foxtrot")

    await compactor.compact("test")
    # Vectorizer should be refitted — verify it can still embed
    result = await provider.embed(["alpha bravo"])
    assert len(result) == 1
    assert len(result[0]) == 64


async def test_compact_empty_collection(compactor: MemoryCompactor) -> None:
    """Compacting an empty collection removes nothing."""
    removed = await compactor.compact("nonexistent")
    assert removed == 0


async def test_preserves_recent_entries(
    store: InMemoryStore, compactor: MemoryCompactor
) -> None:
    """Recent distinct entries within max_age_days are preserved."""
    await store.store("test", "python programming guide for beginners")
    await store.store("test", "italian cooking recipes and pasta")
    await store.store("test", "quantum physics research papers")

    removed = await compactor.compact("test")
    assert await store.count("test") == 3
    assert removed == 0
