"""Tests for TF-IDF embedding provider."""

from __future__ import annotations

import math

import pytest

from openhydra.memory.embeddings import TfidfEmbeddingProvider


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


@pytest.fixture
def provider() -> TfidfEmbeddingProvider:
    return TfidfEmbeddingProvider(max_features=128)


async def test_dimensions(provider: TfidfEmbeddingProvider) -> None:
    assert provider.dimensions == 128


async def test_embed_single_text(provider: TfidfEmbeddingProvider) -> None:
    embeddings = await provider.embed(["hello world"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 128


async def test_embed_multiple_texts(provider: TfidfEmbeddingProvider) -> None:
    texts = ["python programming", "javascript coding", "rust systems"]
    embeddings = await provider.embed(texts)
    assert len(embeddings) == 3
    for emb in embeddings:
        assert len(emb) == 128


async def test_similar_texts_higher_similarity(provider: TfidfEmbeddingProvider) -> None:
    texts = [
        "python machine learning data science",
        "python data analysis statistics",
        "cooking recipes italian food",
    ]
    embeddings = await provider.embed(texts)
    sim_related = _cosine_similarity(embeddings[0], embeddings[1])
    sim_unrelated = _cosine_similarity(embeddings[0], embeddings[2])
    assert sim_related > sim_unrelated


async def test_empty_corpus() -> None:
    provider = TfidfEmbeddingProvider(max_features=64)
    embeddings = await provider.embed([])
    assert embeddings == []


async def test_refit_on_new_texts(provider: TfidfEmbeddingProvider) -> None:
    # First batch
    emb1 = await provider.embed(["alpha beta"])
    assert len(emb1[0]) == 128

    # Second batch with new vocabulary
    emb2 = await provider.embed(["gamma delta"])
    assert len(emb2[0]) == 128

    # Re-embed first text — should still work after refit
    emb3 = await provider.embed(["alpha beta"])
    assert len(emb3[0]) == 128
