"""TF-IDF embedding provider for local vector search."""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer


class TfidfEmbeddingProvider:
    """Embedding provider using scikit-learn TF-IDF vectorizer.

    Refits the vectorizer when new texts are added. Suitable for
    local use with <10K entries.
    """

    def __init__(self, max_features: int = 512) -> None:
        self._max_features = max_features
        self._vectorizer = TfidfVectorizer(max_features=max_features)
        self._corpus: list[str] = []
        self._fitted = False

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._max_features

    def rebuild_corpus(self, texts: list[str]) -> None:
        """Replace the entire corpus and refit the vectorizer."""
        self._corpus = list(texts)
        if self._corpus:
            self._vectorizer = TfidfVectorizer(max_features=self._max_features)
            self._vectorizer.fit(self._corpus)
            self._fitted = True
        else:
            self._vectorizer = TfidfVectorizer(max_features=self._max_features)
            self._fitted = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate TF-IDF embeddings for a list of texts.

        New texts are added to the corpus and the vectorizer is refit.
        """
        new_texts = [t for t in texts if t not in self._corpus]
        if new_texts or not self._fitted:
            self._corpus.extend(new_texts)
            if self._corpus:
                self._vectorizer.fit(self._corpus)
                self._fitted = True

        if not self._fitted:
            # Empty corpus — return zero vectors
            return [[0.0] * self._max_features for _ in texts]

        matrix = self._vectorizer.transform(texts)
        # Pad to max_features if vocabulary is smaller
        result: list[list[float]] = []
        for i in range(matrix.shape[0]):
            row = matrix[i].toarray()[0].tolist()
            if len(row) < self._max_features:
                row.extend([0.0] * (self._max_features - len(row)))
            result.append(row)
        return result
