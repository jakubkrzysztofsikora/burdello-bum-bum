"""Vector embedding utilities using sentence-transformers.

Provides functions to encode text into dense vectors, compute cosine similarity,
and batch-process multiple texts efficiently.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton for the embedding model
# ---------------------------------------------------------------------------

_model: Any | None = None
_model_name: str = "nomic-ai/nomic-embed-text-v2-moe"


def _get_model() -> Any:
    """Return the cached sentence-transformers model, loading if necessary.

    Uses lazy initialisation to avoid heavy import / load at module level.

    Returns:
        A ``SentenceTransformer`` model instance.
    """
    global _model  # noqa: PLW0603

    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", _model_name)
        _model = SentenceTransformer(_model_name, trust_remote_code=True)
        logger.info("Embedding model loaded successfully")

    return _model


async def get_embedding(text: str) -> list[float]:
    """Encode a single text string into a 768-dim embedding vector.

    Args:
        text: The input text to embed.

    Returns:
        A list of 768 float values representing the dense embedding.
    """
    if not text or not text.strip():
        logger.warning("get_embedding: empty text provided, returning zero vector")
        return [0.0] * 768

    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector (must have same length as *a*).

    Returns:
        Cosine similarity in the range ``[-1, 1]``.
    """
    vec_a = np.asarray(a, dtype=np.float32)
    vec_b = np.asarray(b, dtype=np.float32)

    if vec_a.shape != vec_b.shape:
        raise ValueError(
            f"Vector shapes do not match: {vec_a.shape} vs {vec_b.shape}"
        )

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


async def batch_embed(texts: list[str]) -> list[list[float]]:
    """Encode a batch of texts into embedding vectors efficiently.

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
        return [[0.0] * 768 for _ in texts]

    model = _get_model()
    embeddings = model.encode(
        non_empty_texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )

    result: list[list[float]] = [[0.0] * 768 for _ in texts]
    for idx, emb_idx in enumerate(non_empty_indices):
        result[emb_idx] = embeddings[idx].tolist()

    return result
