"""Process-wide cache for sentence-transformers models.

The chunker (semantic boundary detection) and the embedder both use the same
``BB_EMBEDDING_MODEL``. Loading it separately in each doubles a worker child's
resident memory (~1.5GB per copy). Sharing one instance per process keeps the
worker within its memory cap.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, Any] = {}


def get_sentence_transformer(model_name: str) -> Any:
    """Return a cached ``SentenceTransformer``, loading it once per process.

    Args:
        model_name: HuggingFace / sentence-transformers model identifier.

    Returns:
        A shared ``SentenceTransformer`` instance.
    """
    model = _MODEL_CACHE.get(model_name)
    if model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading shared embedding model: %s", model_name)
        model = SentenceTransformer(model_name, trust_remote_code=True)
        _MODEL_CACHE[model_name] = model
    return model
