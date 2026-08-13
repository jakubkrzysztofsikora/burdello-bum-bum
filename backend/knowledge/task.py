"""Knowledge-base Celery task: cluster atoms → build tree → draft summaries.

Run periodically (or on demand) to (re)build the KB tree from
``MiningResult(miner_type='knowledge')`` rows. Idempotent: nodes are
keyed by ``mechanical_key`` so a re-run updates existing nodes instead
of creating duplicates, and human-published nodes keep their status.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.core.database import AsyncSessionLocal
from backend.core.models import KbNode, KbNodeSource, MiningResult
from backend.knowledge.clusterer import Atom, cluster_atoms, embed_atoms
from backend.knowledge.draft_generator import generate_node_summary
from backend.knowledge.hierarchy import HierNode, build_hierarchy

logger = logging.getLogger(__name__)


# Confidence gate below which an atom never enters the KB.
_MIN_ATOM_CONFIDENCE = 0.6
# Source-evidence count that auto-promotes a draft node to published.
_AUTO_PUBLISH_EVIDENCE = 2


def _load_atoms(records: list[MiningResult]) -> list[Atom]:
    """Convert ``MiningResult`` rows into ``Atom`` objects.

    Args:
        records: MiningResult rows whose ``miner_type='knowledge'``.

    Returns:
        Flat list of atoms with confidence filtered.
    """
    atoms: list[Atom] = []
    for record in records:
        data = record.result_data or {}
        for raw in data.get("atoms", []):
            confidence = float(raw.get("confidence") or 0.0)
            if confidence < _MIN_ATOM_CONFIDENCE:
                continue
            atoms.append(
                Atom(
                    atom_id=str(uuid.uuid4()),
                    transcript_id=record.transcript_id,
                    chunk_id=None,
                    project_id=None,
                    name=str(raw.get("name", "")).strip(),
                    kind=str(raw.get("kind", "tool")).strip(),
                    summary=str(raw.get("summary", "")).strip(),
                    category_hint=str(raw.get("category_hint", "")).strip(),
                    outcome=raw.get("outcome"),
                    confidence=confidence,
                )
            )
    return atoms


async def _attach_evidence(
    db: Any,
    leaf_nodes: list[HierNode],
) -> None:
    """Populate ``KbNodeSource`` rows for each leaf node.

    Args:
        db: Async SQLAlchemy session.
        leaf_nodes: Leaf-level ``HierNode`` records carrying atoms.
    """
    for leaf in leaf_nodes:
        node = (
            await db.execute(
                select(KbNode).where(KbNode.slug == leaf.slug)
            )
        ).scalar_one_or_none()
        if node is None:
            continue

        # Distinct (transcript_id, evidence_type, outcome) keys.
        seen: set[tuple[Any, str, str | None]] = set()
        rows: list[dict[str, Any]] = []
        for atom in leaf.atoms:
            key = (atom.transcript_id, leaf.node_type, atom.outcome)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "node_id": node.id,
                    "transcript_id": atom.transcript_id,
                    "chunk_id": atom.chunk_id,
                    "project_id": atom.project_id,
                    "excerpt": (atom.summary or "")[:500],
                    "evidence_type": "worked_example",
                    "outcome": atom.outcome,
                    "confidence": atom.confidence,
                }
            )
        if not rows:
            continue

        # Upsert by (node_id, chunk_id) — chunk_id may be null so use
        # INSERT ... ON CONFLICT DO NOTHING to keep it idempotent.
        stmt = pg_insert(KbNodeSource).values(rows)
        await db.execute(stmt)


async def _persist_nodes(
    db: Any,
    nodes: list[HierNode],
    leaf_summaries: dict[str, str | None],
    engine: Any,
) -> int:
    """Upsert ``KbNode`` rows for every ``HierNode``.

    Args:
        db: Async SQLAlchemy session.
        nodes: All ``HierNode`` records (roots + subcategories + leaves).
        leaf_summaries: Pre-generated summaries keyed by leaf slug.
        engine: Embedding engine used to populate the node's vector.

    Returns:
        Number of leaf nodes persisted (for logging).
    """
    slug_to_node: dict[str, KbNode] = {}
    leaf_count = 0

    # First pass: roots (no parent_slug).
    for node in nodes:
        if node.node_type != "category":
            continue
        existing = (
            await db.execute(
                select(KbNode).where(KbNode.slug == node.slug)
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = KbNode(
                slug=node.slug,
                title=node.title,
                node_type=node.node_type,
                parent_id=None,
                summary=node.summary_seed,
                mechanical_key=node.mechanical_key,
                top_terms=node.top_terms,
                confidence=node.confidence,
                status="published",
            )
            db.add(existing)
            await db.flush()
        slug_to_node[node.slug] = existing

    # Second pass: subcategories + leaves, in order.
    for node in nodes:
        if node.node_type == "category":
            continue
        parent_id = (
            slug_to_node[node.parent_slug].id
            if node.parent_slug in slug_to_node
            else None
        )
        summary_text = (
            leaf_summaries.get(node.slug)
            if node.node_type == "topic"
            else None
        )
        existing = (
            await db.execute(
                select(KbNode).where(KbNode.slug == node.slug)
            )
        ).scalar_one_or_none()

        leaf_text = _node_embedding_text(node, summary_text)
        embedding_vec = (
            engine.embed(leaf_text) if leaf_text else None
        )

        if existing is None:
            existing = KbNode(
                slug=node.slug,
                title=node.title,
                node_type=node.node_type,
                parent_id=parent_id,
                summary=summary_text or node.summary_seed or None,
                mechanical_key=node.mechanical_key,
                top_terms=node.top_terms,
                confidence=node.confidence,
                status="draft",
                source_evidence_count=len(node.atoms),
                embedding=embedding_vec,
            )
            db.add(existing)
            await db.flush()
        else:
            existing.title = node.title
            existing.parent_id = parent_id
            existing.top_terms = node.top_terms
            existing.confidence = node.confidence
            existing.source_evidence_count = max(
                existing.source_evidence_count, len(node.atoms)
            )
            # Preserve human-published status; only auto-promote drafts.
            if existing.status == "draft" and (
                len(node.atoms) >= _AUTO_PUBLISH_EVIDENCE
            ):
                existing.status = "published"
            if summary_text and not existing.summary:
                existing.summary = summary_text
            if embedding_vec is not None and existing.embedding is None:
                existing.embedding = embedding_vec
        slug_to_node[node.slug] = existing
        if node.node_type == "topic":
            leaf_count += 1

    return leaf_count


def _node_embedding_text(node: HierNode, summary: str | None) -> str | None:
    """Concatenate the fields used to embed a node for vector search.

    Args:
        node: Leaf node being persisted.
        summary: LLM-generated summary, if available.

    Returns:
        Text suitable for embedding, or ``None`` if the node has nothing
        meaningful to embed.
    """
    parts: list[str] = []
    if summary:
        parts.append(summary)
    if node.title:
        parts.append(node.title)
    if node.top_terms:
        parts.append(" ".join(node.top_terms))
    text = " \n".join(parts).strip()
    return text or None


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def kb_cluster_task(self) -> dict[str, Any]:
    """Build / refresh the KB tree from current knowledge atoms.

    Returns:
        Dict with ``atoms``, ``clusters``, ``nodes``, ``leaves`` counts
        and ``status: ok | skipped | error``.
    """
    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            # Always ensure the 10 root nodes exist so the UI shows
            # structure even before any atoms accumulate.
            from backend.knowledge.seeds import CATEGORY_SEEDS

            for seed in CATEGORY_SEEDS:
                existing = (
                    await db.execute(
                        select(KbNode).where(KbNode.slug == seed.slug)
                    )
                ).scalar_one_or_none()
                if existing is None:
                    db.add(
                        KbNode(
                            slug=seed.slug,
                            title=seed.title,
                            node_type="category",
                            parent_id=None,
                            summary=seed.summary,
                            mechanical_key=f"root:{seed.slug}",
                            status="published",
                            confidence=1.0,
                        )
                    )

            rows = (
                await db.execute(
                    select(MiningResult).where(
                        MiningResult.miner_type == "knowledge"
                    )
                )
            ).scalars().all()

            atoms = _load_atoms(list(rows))
            if len(atoms) < 2:
                await db.commit()
                return {
                    "status": "skipped",
                    "reason": "not_enough_atoms",
                    "atoms": len(atoms),
                    "clusters": 0,
                    "nodes": len(CATEGORY_SEEDS),
                    "leaves": 0,
                }

            from backend.pipeline.embedding import EmbeddingEngine

            engine = EmbeddingEngine()
            embed_atoms(atoms, engine)

            clusters = cluster_atoms(atoms)
            nodes = build_hierarchy(clusters)
            leaf_nodes = [n for n in nodes if n.node_type == "topic"]

            leaf_summaries: dict[str, str | None] = {}
            for leaf in leaf_nodes:
                leaf_summaries[leaf.slug] = await generate_node_summary(leaf)

            leaf_count = await _persist_nodes(db, nodes, leaf_summaries, engine)
            await _attach_evidence(db, leaf_nodes)
            await db.commit()

            return {
                "status": "ok",
                "atoms": len(atoms),
                "clusters": len(clusters),
                "nodes": len(nodes),
                "leaves": leaf_count,
            }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("kb_cluster_task: failed")
        raise self.retry(exc=exc) from exc