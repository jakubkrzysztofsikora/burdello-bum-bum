"""Knowledge-base retrieval: cosine search over published KbNode embeddings."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import select

from backend.core.models import KbNode

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.pipeline.embedding import EmbeddingEngine

logger = logging.getLogger(__name__)


@dataclass
class KbHit:
    """A KB node matched against a query."""

    slug: str
    title: str
    summary: str | None
    top_terms: list[str]
    score: float


async def search_kb_nodes(
    db: "AsyncSession",
    question: str,
    engine: "EmbeddingEngine",
    *,
    top_k: int = 3,
    min_score: float = 0.35,
) -> list[KbHit]:
    """Find published KB nodes whose embedding is most similar to the question.

    Args:
        db: Async SQLAlchemy session.
        question: User question (also used as the embedding input).
        engine: Embedding engine matching the one used at write time.
        top_k: Maximum nodes to return.
        min_score: Minimum cosine similarity to include a hit.

    Returns:
        Ranked list of ``KbHit`` records (highest score first). Empty
        when the KB has no published nodes with embeddings yet.
    """
    if not question or not question.strip():
        return []

    rows = (
        await db.execute(
            select(KbNode).where(
                KbNode.status == "published",
                KbNode.embedding.isnot(None),
            )
        )
    ).scalars().all()

    if not rows:
        return []

    q_vec = np.asarray(engine.embed(question), dtype=np.float32)

    scored: list[KbHit] = []
    for node in rows:
        emb = node.embedding
        if emb is None:
            continue
        n_vec = np.asarray(emb, dtype=np.float32)
        denom = float(np.linalg.norm(q_vec) * np.linalg.norm(n_vec))
        if denom == 0:
            continue
        score = float(np.dot(q_vec, n_vec) / denom)
        if score < min_score:
            continue
        scored.append(
            KbHit(
                slug=node.slug,
                title=node.title,
                summary=node.summary,
                top_terms=list(node.top_terms or []),
                score=score,
            )
        )

    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[:top_k]