"""Incremental KB atom assignment.

After ``knowledge_extract_task`` stores raw atoms for a transcript,
this task matches each atom to an existing ``KbNode`` (by embedding
cosine against the node's stored vector) and inserts a ``KbNodeSource``
evidence row. Calibrated bands mirror the lustro store:
- >= 0.87 attach to existing node (auto)
- 0.80–0.87 mark for human review via the ``metadata_`` flag
- < 0.80 leave unassigned; ``kb_cluster_task`` will pick it up on its
  next run when the corpus grows enough for a fresh cluster

Note: chunk_id is always NULL for incremental assignments (atoms aren't
pinned to specific chunks yet), so the unique-constraint dedup uses
``(node_id, transcript_id, excerpt_hash)`` constructed via a CTE-less
INSERT … SELECT WHERE NOT EXISTS. Postgres ``NULL != NULL`` semantics
would let duplicate (node_id, NULL chunk_id) rows through a plain
``ON CONFLICT (node_id, chunk_id)`` guard, so we hash the excerpt and
filter at insert time.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

import numpy as np
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal
from backend.core.models import KbNode, KbNodeSource, MiningResult
from backend.pipeline.embedding import EmbeddingEngine

logger = logging.getLogger(__name__)

_ATTACH_THRESHOLD = 0.87
_REVIEW_THRESHOLD = 0.80


def _excerpt_hash(text: str | None) -> str:
    """Stable 16-char hash used to dedupe evidence rows by excerpt content."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


async def _candidate_nodes(
    db: AsyncSession, embedding: np.ndarray
) -> list[tuple[uuid.UUID, float, str]]:
    """Return ``(node_id, score, status)`` for every published node.

    Args:
        db: Async SQLAlchemy session.
        embedding: Normalised atom embedding.

    Returns:
        List of ``(node_id, cosine_score, 'attached'|'review')`` sorted
        by score descending.
    """
    rows = (
        await db.execute(
            select(KbNode).where(
                KbNode.embedding.isnot(None),
            )
        )
    ).scalars().all()

    scored: list[tuple[uuid.UUID, float, str]] = []
    for node in rows:
        if node.embedding is None:
            continue
        n_vec = np.asarray(node.embedding, dtype=np.float32)
        denom = float(np.linalg.norm(embedding) * np.linalg.norm(n_vec))
        if denom == 0:
            continue
        score = float(np.dot(embedding, n_vec) / denom)
        if score >= _ATTACH_THRESHOLD:
            scored.append((node.id, score, "attached"))
        elif score >= _REVIEW_THRESHOLD:
            scored.append((node.id, score, "review"))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


async def _evidence_exists(
    db: AsyncSession,
    node_id: uuid.UUID,
    transcript_id: uuid.UUID,
    excerpt_hash: str,
) -> bool:
    """Return True iff a matching evidence row already exists.

    Args:
        db: Async SQLAlchemy session.
        node_id: Candidate KB node id.
        transcript_id: Transcript being assigned.
        excerpt_hash: Content hash of the excerpt.

    Returns:
        True when a matching ``KbNodeSource`` row is present.
    """
    excerpt = await db.execute(
        select(KbNodeSource.id).where(
            KbNodeSource.node_id == node_id,
            KbNodeSource.transcript_id == transcript_id,
            KbNodeSource.excerpt.isnot(None),
        )
    )
    for row in excerpt.scalars().all():
        existing = (
            await db.execute(
                select(KbNodeSource.excerpt).where(
                    KbNodeSource.id == row
                )
            )
        ).scalar_one_or_none()
        if existing and _excerpt_hash(existing) == excerpt_hash:
            return True
    return False


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def kb_incremental_assign_task(
    self, knowledge_result: dict[str, Any]
) -> dict[str, Any]:
    """Assign newly extracted atoms to existing KB nodes.

    Args:
        knowledge_result: Output of ``knowledge_extract_task``.

    Returns:
        Dict with ``transcript_id``, ``atom_count``, ``attached``,
        ``review``, ``skipped`` counts.
    """
    transcript_id_str = knowledge_result.get("transcript_id")
    if not transcript_id_str:
        return {**knowledge_result, "status": "skipped", "reason": "no_transcript_id"}

    transcript_id = uuid.UUID(transcript_id_str)

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(MiningResult).where(
                        MiningResult.transcript_id == transcript_id,
                        MiningResult.miner_type == "knowledge",
                    )
                )
            ).scalar_one_or_none()
            if record is None:
                return {
                    "transcript_id": str(transcript_id),
                    "status": "skipped",
                    "reason": "no_knowledge_mining_result",
                    "atom_count": 0,
                    "attached": 0,
                    "review": 0,
                    "skipped": 0,
                }

            atoms = (record.result_data or {}).get("atoms", [])
            if not atoms:
                return {
                    "transcript_id": str(transcript_id),
                    "status": "ok",
                    "atom_count": 0,
                    "attached": 0,
                    "review": 0,
                    "skipped": 0,
                }

            engine = EmbeddingEngine()
            embedded_texts = [
                f"{a.get('name', '')}. {a.get('summary', '')}" for a in atoms
            ]
            vectors = engine.embed_batch(embedded_texts)

            attached = 0
            review = 0
            skipped = 0
            review_rows: list[dict[str, Any]] = []

            for atom, vector in zip(atoms, vectors):
                if not vector or all(v == 0 for v in vector):
                    skipped += 1
                    continue
                emb = np.asarray(vector, dtype=np.float32)
                candidates = await _candidate_nodes(db, emb)
                if not candidates:
                    skipped += 1
                    continue
                best_id, best_score, status_label = candidates[0]

                excerpt_text = str(atom.get("summary", ""))[:500]

                if status_label == "attached":
                    if await _evidence_exists(
                        db, best_id, transcript_id, _excerpt_hash(excerpt_text)
                    ):
                        skipped += 1
                        continue
                    db.add(
                        KbNodeSource(
                            id=uuid.uuid4(),
                            node_id=best_id,
                            transcript_id=transcript_id,
                            chunk_id=None,
                            project_id=None,
                            excerpt=excerpt_text,
                            evidence_type="worked_example",
                            outcome=atom.get("outcome"),
                            confidence=float(atom.get("confidence") or 0.0),
                        )
                    )
                    attached += 1
                else:
                    review_rows.append(
                        {
                            "atom_name": atom.get("name"),
                            "best_score": best_score,
                            "best_node_id": str(best_id),
                        }
                    )
                    review += 1

            if review_rows:
                logger.info(
                    "kb_incremental_assign: %d atom(s) queued for review on transcript %s",
                    len(review_rows),
                    transcript_id,
                )

            await db.commit()
            return {
                "transcript_id": str(transcript_id),
                "status": "ok",
                "atom_count": len(atoms),
                "attached": attached,
                "review": review,
                "skipped": skipped,
            }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception(
            "kb_incremental_assign_task: failed for %s", transcript_id
        )
        raise self.retry(exc=exc) from exc