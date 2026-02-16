"""Tests for SqliteMemoryStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from openhydra.memory.backends.sqlite import SqliteMemoryStore
from openhydra.memory.embeddings import TfidfEmbeddingProvider


@pytest.fixture
async def store(tmp_path: Path) -> SqliteMemoryStore:
    s = SqliteMemoryStore(
        path=tmp_path / "memory.db",
        embedding_provider=TfidfEmbeddingProvider(max_features=64),
    )
    await s.connect()
    yield s
    await s.close()


async def test_store_and_get(store: SqliteMemoryStore) -> None:
    entry_id = await store.store("test", "hello world", metadata={"key": "value"})
    entry = await store.get("test", entry_id)
    assert entry is not None
    assert entry.content == "hello world"
    assert entry.metadata == {"key": "value"}


async def test_get_not_found(store: SqliteMemoryStore) -> None:
    result = await store.get("test", "nonexistent")
    assert result is None


async def test_search_by_similarity(store: SqliteMemoryStore) -> None:
    await store.store("docs", "python programming language")
    await store.store("docs", "python data science analysis")
    await store.store("docs", "italian cooking recipes pasta")

    results = await store.search("docs", "python coding")
    assert len(results) >= 2
    assert any("python" in r.content for r in results[:2])


async def test_search_empty_collection(store: SqliteMemoryStore) -> None:
    results = await store.search("empty", "query")
    assert results == []


async def test_delete(store: SqliteMemoryStore) -> None:
    entry_id = await store.store("test", "to be deleted")
    assert await store.delete("test", entry_id) is True
    assert await store.get("test", entry_id) is None
    assert await store.delete("test", entry_id) is False


async def test_list_collections(store: SqliteMemoryStore) -> None:
    await store.store("alpha", "content a")
    await store.store("beta", "content b")
    collections = await store.list_collections()
    assert "alpha" in collections
    assert "beta" in collections


async def test_metadata_filtering(store: SqliteMemoryStore) -> None:
    await store.store("docs", "python guide", metadata={"type": "tutorial"})
    await store.store("docs", "python reference", metadata={"type": "reference"})
    await store.store("docs", "python overview", metadata={"type": "tutorial"})

    results = await store.search("docs", "python", filters={"type": "tutorial"})
    assert all(r.metadata.get("type") == "tutorial" for r in results)


async def test_persistence(tmp_path: Path) -> None:
    provider = TfidfEmbeddingProvider(max_features=64)
    path = tmp_path / "persist.db"

    # Store data
    store1 = SqliteMemoryStore(path=path, embedding_provider=provider)
    await store1.connect()
    entry_id = await store1.store("test", "persistent data")
    await store1.close()

    # Reopen and verify
    store2 = SqliteMemoryStore(path=path, embedding_provider=provider)
    await store2.connect()
    entry = await store2.get("test", entry_id)
    assert entry is not None
    assert entry.content == "persistent data"
    await store2.close()
