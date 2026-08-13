"""API router for Knowledge Base endpoints.

Provides:
- ``GET /kb/tree`` — full tree (lightweight node summaries).
- ``GET /kb/nodes/{slug}`` — node detail with evidence links + children.
- ``GET /kb/entities`` — paginated entity index, optionally filtered by type.
- ``GET /kb/entities/{slug}`` — entity detail with mention timeline.

All read-only. The cluster task is exposed separately under /mining
for on-demand rebuilds.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.core.models import KbEntity, KbEntityMention, KbNode, KbNodeSource
from backend.core.schemas import (
    KbEntityDetail,
    KbEntityListResponse,
    KbEntityMentionItem,
    KbEntitySummary,
    KbEvidenceItem,
    KbNodeDetail,
    KbNodeSummary,
    KbTreeResponse,
)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


def _node_to_summary(node: KbNode) -> KbNodeSummary:
    return KbNodeSummary(
        slug=node.slug,
        title=node.title,
        node_type=node.node_type,
        parent_slug=None,  # filled in by caller via slug map
        status=node.status,
        top_terms=list(node.top_terms or []),
        confidence=float(node.confidence or 0.0),
        source_evidence_count=node.source_evidence_count,
    )


@router.get("/tree", response_model=KbTreeResponse)
async def get_kb_tree(
    db: AsyncSession = Depends(get_db),
) -> KbTreeResponse:
    """Return the full KB tree as nested summaries."""
    rows = (
        await db.execute(
            select(KbNode).order_by(
                KbNode.node_type.desc(), KbNode.slug.asc()
            )
        )
    ).scalars().all()

    if not rows:
        return KbTreeResponse(nodes=[], total_nodes=0, total_published=0)

    slug_to_parent: dict[str, str | None] = {}
    for row in rows:
        slug_to_parent[row.slug] = row.parent.slug if row.parent else None

    node_map: dict[str, KbNodeSummary] = {}
    for row in rows:
        node_map[row.slug] = _node_to_summary(row)

    for slug, parent_slug in slug_to_parent.items():
        if parent_slug is not None and parent_slug in node_map:
            node_map[parent_slug].children.append(node_map[slug])
        node_map[slug].parent_slug = parent_slug

    roots = [
        node_map[row.slug]
        for row in rows
        if slug_to_parent.get(row.slug) is None
    ]
    published = sum(1 for r in rows if r.status == "published")
    return KbTreeResponse(
        nodes=roots,
        total_nodes=len(rows),
        total_published=published,
    )


# ---------------------------------------------------------------------------
# Node detail
# ---------------------------------------------------------------------------


async def _build_node_detail(
    db: AsyncSession, node: KbNode
) -> KbNodeDetail:
    """Assemble a ``KbNodeDetail`` from a row + its evidence + children."""
    evidence_rows = (
        await db.execute(
            select(KbNodeSource)
            .where(KbNodeSource.node_id == node.id)
            .order_by(KbNodeSource.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    evidence = [
        KbEvidenceItem(
            id=str(e.id),
            transcript_id=str(e.transcript_id) if e.transcript_id else None,
            project_id=str(e.project_id) if e.project_id else None,
            excerpt=e.excerpt,
            evidence_type=e.evidence_type,
            outcome=e.outcome,
            confidence=e.confidence,
            created_at=e.created_at,
        )
        for e in evidence_rows
    ]

    child_rows = (
        await db.execute(
            select(KbNode)
            .where(KbNode.parent_id == node.id)
            .order_by(KbNode.slug.asc())
        )
    ).scalars().all()

    children: list[KbNodeDetail] = []
    for child in child_rows:
        children.append(await _build_node_detail(db, child))

    return KbNodeDetail(
        slug=node.slug,
        title=node.title,
        node_type=node.node_type,
        parent_slug=node.parent.slug if node.parent else None,
        status=node.status,
        summary=node.summary,
        top_terms=list(node.top_terms or []),
        confidence=float(node.confidence or 0.0),
        source_evidence_count=node.source_evidence_count,
        mechanical_key=node.mechanical_key,
        updated_at=node.updated_at,
        evidence=evidence,
        children=children,
    )


@router.get("/nodes/{slug}", response_model=KbNodeDetail)
async def get_kb_node(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> KbNodeDetail:
    """Return a node with its evidence links + immediate children."""
    node = (
        await db.execute(
            select(KbNode).where(KbNode.slug == slug)
        )
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(
            status_code=404, detail=f"KB node {slug!r} not found"
        )
    return await _build_node_detail(db, node)


# ---------------------------------------------------------------------------
# Entity index
# ---------------------------------------------------------------------------


@router.get("/entities", response_model=KbEntityListResponse)
async def list_kb_entities(
    entity_type: str | None = Query(
        None,
        description=(
            "Filter by entity type: tool, library, framework, "
            "pattern, technique, concept."
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> KbEntityListResponse:
    """Return a paginated entity index."""
    base = select(KbEntity).order_by(KbEntity.mention_count.desc())
    if entity_type:
        base = base.where(KbEntity.entity_type == entity_type)

    rows = (
        await db.execute(base.offset(offset).limit(limit))
    ).scalars().all()
    total = (
        await db.execute(
            select(func.count(KbEntity.id))
            .where(
                KbEntity.entity_type == entity_type
                if entity_type
                else KbEntity.id.isnot(None)
            )
        )
    ).scalar() or 0

    return KbEntityListResponse(
        entities=[
            KbEntitySummary(
                id=str(r.id),
                canonical_name=r.canonical_name,
                entity_type=r.entity_type,
                description=r.description,
                mention_count=r.mention_count,
                aliases=list(r.aliases or []),
            )
            for r in rows
        ],
        total=int(total),
    )


@router.get("/entities/{slug:path}", response_model=KbEntityDetail)
async def get_kb_entity(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> KbEntityDetail:
    """Return one entity's full detail + mention timeline."""
    entity = (
        await db.execute(
            select(KbEntity).where(KbEntity.canonical_name == slug)
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(
            status_code=404, detail=f"KB entity {slug!r} not found"
        )

    mentions = (
        await db.execute(
            select(KbEntityMention)
            .where(KbEntityMention.entity_id == entity.id)
            .order_by(KbEntityMention.first_seen_at.desc().nullslast())
            .limit(200)
        )
    ).scalars().all()

    return KbEntityDetail(
        id=str(entity.id),
        canonical_name=entity.canonical_name,
        entity_type=entity.entity_type,
        description=entity.description,
        how_used=entity.how_used,
        why_used=entity.why_used,
        mention_count=entity.mention_count,
        aliases=list(entity.aliases or []),
        mentions=[
            KbEntityMentionItem(
                id=str(m.id),
                transcript_id=str(m.transcript_id) if m.transcript_id else None,
                project_id=str(m.project_id) if m.project_id else None,
                node_slug=None,
                context_excerpt=m.context_excerpt,
                outcome=m.outcome,
                first_seen_at=m.first_seen_at,
                last_seen_at=m.last_seen_at,
            )
            for m in mentions
        ],
    )