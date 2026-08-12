"""Recreate the Qdrant collection and bulk-load all chunks from PostgreSQL.

The vector store's on-disk HNSW index can degrade under memory pressure, leaving
queries to fall back to full scans. This script rebuilds a clean collection with
on-disk HNSW + on-disk vectors and streams every persisted chunk (with its stored
embedding) from Postgres into it — no embeddings are recomputed.

Usage:
    python -m backend.scripts.reindex_qdrant [--batch 1000] [--drop-existing] [--resume]

The collection is created fresh (or recreated when ``--drop-existing``) and every
chunk row is upserted. Safe to re-run; upserts are idempotent. Use ``--resume``
to continue a partially-loaded run without dropping the collection.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import get_settings
from backend.core.database import async_engine
from backend.core.models import Chunk
from backend.search.engine import VECTOR_DIM

logger = logging.getLogger(__name__)

SessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def recreate_collection(client: QdrantClient, collection: str) -> None:
    """Drop and recreate the collection with on-disk HNSW + on-disk vectors."""
    try:
        client.delete_collection(collection)
        logger.info("deleted existing collection %r", collection)
    except Exception:
        logger.info("collection %r did not exist; creating fresh", collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE, on_disk=True),
        hnsw_config={"m": 16, "ef_construct": 100, "on_disk": True},
    )
    for field in (
        "transcript_id",
        "metadata.project_id",
        "metadata.source_type",
        "metadata.created_at",
    ):
        client.create_payload_index(
            collection_name=collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    logger.info("created collection %r (dim=%d, cosine, on-disk)", collection, VECTOR_DIM)


async def reindex(batch_size: int, resume: bool = False) -> int:
    settings = get_settings()
    client = QdrantClient(url=settings.QDRANT_URL, timeout=300)
    if not resume:
        await recreate_collection(client, settings.QDRANT_COLLECTION)

    total = 0
    async with SessionLocal() as db:
        # Stream every chunk with its embedding and parent transcript id.
        cursor: Any = None
        while True:
            stmt = (
                select(Chunk.id, Chunk.transcript_id, Chunk.text, Chunk.embedding, Chunk.metadata_)
                .order_by(Chunk.id)
                .limit(batch_size)
            )
            if cursor is not None:
                stmt = stmt.where(Chunk.id > cursor)
            rows = (await db.execute(stmt)).all()
            if not rows:
                break

            points = [
                PointStruct(
                    id=str(row.id),
                    vector=[float(v) for v in row.embedding],
                    payload={
                        "transcript_id": str(row.transcript_id),
                        "text": row.text,
                        "metadata": row.metadata_ or {},
                    },
                )
                for row in rows
                if row.embedding is not None
            ]
            if points:
                client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points, wait=False)
                total += len(points)
                logger.info("upserted %d points (running total %d)", len(points), total)

            cursor = rows[-1].id

    logger.info("reindex complete: %d points", total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild Qdrant collection from Postgres chunks")
    parser.add_argument("--batch", type=int, default=1000)
    parser.add_argument("--resume", action="store_true", help="Skip collection recreation; only upsert")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(reindex(args.batch, resume=args.resume))


if __name__ == "__main__":
    main()