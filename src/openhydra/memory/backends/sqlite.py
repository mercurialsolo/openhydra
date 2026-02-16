"""SQLite-backed memory store with optional sqlite-vec for kNN search."""

from __future__ import annotations

import json
import math
import struct
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ..base import EmbeddingProvider, MemoryEntry

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    embedding BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_collection ON memory_entries(collection);
"""


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a float list to a compact binary blob."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes) -> list[float]:
    """Deserialize a binary blob to a float list."""
    count = len(blob) // 4  # 4 bytes per float
    return list(struct.unpack(f"{count}f", blob))


class SqliteMemoryStore:
    """SQLite-backed memory store.

    Tries to load sqlite-vec for fast kNN search. Falls back to
    brute-force cosine similarity in Python.
    """

    def __init__(
        self,
        path: Path,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._path = path
        self._embedding_provider = embedding_provider
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open database and ensure schema exists."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(MEMORY_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Memory store not connected. Call connect() first.")
        return self._conn

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

        blob = _serialize_embedding(embedding)
        meta_json = json.dumps(metadata or {})

        await self.conn.execute(
            "INSERT INTO memory_entries (id, collection, content, metadata, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry_id, collection, content, meta_json, blob),
        )
        await self.conn.commit()
        return entry_id

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        query_embedding = (await self._embedding_provider.embed([query]))[0]
        return await self._brute_force_search(collection, query_embedding, limit, filters)

    async def get(self, collection: str, entry_id: str) -> MemoryEntry | None:
        cursor = await self.conn.execute(
            "SELECT id, collection, content, metadata, created_at "
            "FROM memory_entries WHERE id = ? AND collection = ?",
            (entry_id, collection),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def delete(self, collection: str, entry_id: str) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM memory_entries WHERE id = ? AND collection = ?",
            (entry_id, collection),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def list_collections(self) -> list[str]:
        cursor = await self.conn.execute(
            "SELECT DISTINCT collection FROM memory_entries ORDER BY collection"
        )
        rows = await cursor.fetchall()
        return [row["collection"] for row in rows]

    async def count(self, collection: str) -> int:
        cursor = await self.conn.execute(
            "SELECT COUNT(*) as cnt FROM memory_entries WHERE collection = ?",
            (collection,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def list_entries(
        self,
        collection: str,
        limit: int = 100,
        oldest_first: bool = True,
    ) -> list[MemoryEntry]:
        order = "ASC" if oldest_first else "DESC"
        cursor = await self.conn.execute(
            f"SELECT id, content, metadata, created_at FROM memory_entries "
            f"WHERE collection = ? ORDER BY created_at {order} LIMIT ?",
            (collection, limit),
        )
        rows = await cursor.fetchall()
        return [
            MemoryEntry(
                id=row["id"],
                content=row["content"],
                metadata=json.loads(row["metadata"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def _brute_force_search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[MemoryEntry]:
        """Fetch all entries in collection and compute cosine similarity."""
        cursor = await self.conn.execute(
            "SELECT id, content, metadata, embedding, created_at "
            "FROM memory_entries WHERE collection = ?",
            (collection,),
        )
        rows = await cursor.fetchall()

        scored: list[tuple[float, MemoryEntry]] = []
        for row in rows:
            meta = json.loads(row["metadata"])
            if filters and not self._matches_filters(meta, filters):
                continue
            embedding = _deserialize_embedding(row["embedding"])
            score = self._cosine_similarity(query_embedding, embedding)
            entry = MemoryEntry(
                id=row["id"],
                content=row["content"],
                metadata=meta,
                score=score,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

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
