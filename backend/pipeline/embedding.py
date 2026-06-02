"""Embedding generation for transcript chunks.

Provides ``EmbeddingEngine`` which wraps sentence-transformers to produce
768-dimensional dense vectors suitable for Qdrant indexing.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Lazy singleton for the embedding engine instance
_engine_instance: EmbeddingEngine | None = None


class EmbeddingEngine:
    """Embedding engine using sentence-transformers.

    Produces 768-dimensional cosine-normalised embeddings compatible with
    the Qdrant collection configured in ``backend.search.engine``.
    """

    def __init__(self, model_name: str | None = None) -> None:
        """Initialise the embedding engine.

        Args:
            model_name: Sentence-transformers model name. Falls back to
                ``BB_EMBEDDING_MODEL`` from application settings.
        """
        settings = get_settings()
        resolved_model = model_name or settings.BB_EMBEDDING_MODEL

        # Shared per-process model (chunker + embedder reuse one instance).
        from backend.pipeline.model_cache import get_sentence_transformer

        self.model = get_sentence_transformer(resolved_model)
        self.dimension = 768

    def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: Input text to encode.

        Returns:
            A 768-dimensional embedding vector as a list of floats.
        """
        if not text or not text.strip():
            logger.warning("embed: empty text provided, returning zero vector")
            return [0.0] * self.dimension

        vector = self.model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts efficiently.

        Args:
            texts: List of input strings.

        Returns:
            List of embedding vectors, one per input text.
        """
        if not texts:
            return []

        # Filter out empty strings and replace with zero vectors later
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        non_empty_texts = [texts[i] for i in non_empty_indices]

        if not non_empty_texts:
            return [[0.0] * self.dimension for _ in texts]

        embeddings = self.model.encode(
            non_empty_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        result: list[list[float]] = [[0.0] * self.dimension for _ in texts]
        for idx, emb_idx in enumerate(non_empty_indices):
            result[emb_idx] = embeddings[idx].tolist()

        return result

    def embed_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add an ``embedding`` field to each chunk dict.

        Args:
            chunks: List of chunk dicts with at least a ``text`` key.

        Returns:
            The same list with an ``embedding`` key (List[float]) added
            to each dict.
        """
        if not chunks:
            return chunks

        texts = [chunk.get("text", "") for chunk in chunks]
        embeddings = self.embed_batch(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding

        return chunks


def get_embedding_engine() -> EmbeddingEngine:
    """Return a cached ``EmbeddingEngine`` singleton.

    Returns:
        The shared ``EmbeddingEngine`` instance.
    """
    global _engine_instance  # noqa: PLW0603

    if _engine_instance is None:
        _engine_instance = EmbeddingEngine()

    return _engine_instance
