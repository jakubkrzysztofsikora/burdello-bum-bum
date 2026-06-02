"""Hybrid search engine using Qdrant vector search with metadata filtering.

Provides ``HybridSearchEngine`` which combines dense vector search
(768-dim embeddings from nomic-embed-text-v2) with payload filtering
to retrieve relevant transcript chunks.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from backend.core.schemas import SearchResult
from backend.search.vector import get_embedding

logger = logging.getLogger(__name__)

# Vector dimension for nomic-embed-text-v2
VECTOR_DIM = 768


class HybridSearchEngine:
    """Hybrid search engine backed by Qdrant.

    Supports vector similarity search with optional metadata filters,
    nearest-neighbour lookup, and batch indexing of transcript chunks.
    """

    def __init__(self, qdrant_url: str, collection_name: str) -> None:
        """Initialise the search engine.

        Args:
            qdrant_url: Full URL of the Qdrant instance (e.g. ``http://localhost:6333``).
            collection_name: Name of the Qdrant collection to use.
        """
        self.client = QdrantClient(url=qdrant_url)
        self.collection = collection_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SearchResult]:
        """Execute a hybrid vector + filter search.

        1. Embeds the query text into a 768-dim vector.
        2. Searches Qdrant using cosine similarity.
        3. Applies optional payload filters.
        4. Returns scored results.

        Args:
            query: Free-text search query.
            filters: Optional metadata filters (``transcript_id``, ``project_id``, etc.).
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            Ordered list of ``SearchResult`` items (highest score first).
        """
        query_vector = await get_embedding(query)
        qdrant_filter = self._build_filter(filters) if filters else None

        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        search_results: list[SearchResult] = []
        for scored_point in response.points:
            payload = scored_point.payload or {}
            search_results.append(
                SearchResult(
                    chunk_id=uuid.UUID(scored_point.id),
                    transcript_id=uuid.UUID(
                        payload.get("transcript_id", str(uuid.uuid4()))
                    ),
                    text=payload.get("text", ""),
                    score=float(scored_point.score),
                    metadata=payload.get("metadata"),
                )
            )

        logger.info(
            "search: query=%r filters=%r returned=%d",
            query,
            filters,
            len(search_results),
        )
        return search_results

    async def find_similar(
        self,
        transcript_id: str,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Find transcripts similar to the given one.

        Args:
            transcript_id: UUID of the reference transcript.
            limit: Maximum number of similar results.

        Returns:
            Ordered list of similar ``SearchResult`` items.
        """
        # Search for any chunk belonging to the transcript, then use
        # the first chunk's embedding to find neighbours.
        scroll_result = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="transcript_id",
                        match=MatchValue(value=transcript_id),
                    ),
                ]
            ),
            limit=1,
            with_vectors=True,
            with_payload=True,
        )

        points = scroll_result[0]
        if not points:
            logger.warning(
                "find_similar: no chunks found for transcript %s", transcript_id
            )
            return []

        reference_vector = points[0].vector
        response = self.client.query_points(
            collection_name=self.collection,
            query=reference_vector,  # type: ignore[arg-type]
            limit=limit + 1,  # +1 to filter out the query itself
            with_payload=True,
        )

        search_results: list[SearchResult] = []
        for scored_point in response.points:
            # Exclude the reference transcript itself
            payload = scored_point.payload or {}
            if payload.get("transcript_id") == transcript_id:
                continue
            search_results.append(
                SearchResult(
                    chunk_id=uuid.UUID(scored_point.id),
                    transcript_id=uuid.UUID(
                        payload.get("transcript_id", str(uuid.uuid4()))
                    ),
                    text=payload.get("text", ""),
                    score=float(scored_point.score),
                    metadata=payload.get("metadata"),
                )
            )
            if len(search_results) >= limit:
                break

        return search_results

    async def index_chunks(
        self,
        chunks: list[Any],
    ) -> None:
        """Upsert transcript chunks into the Qdrant collection.

        Each chunk is expected to have ``id``, ``transcript_id``, ``text``,
        ``embedding``, and optional ``metadata`` attributes.

        Args:
            chunks: List of chunk objects / dicts to index.
        """
        points: list[PointStruct] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                chunk_id = str(chunk.get("id", uuid.uuid4()))
                transcript_id = str(chunk["transcript_id"])
                text = chunk["text"]
                vector = chunk.get("embedding")
                metadata = chunk.get("metadata", {})
            else:
                chunk_id = str(chunk.id)
                transcript_id = str(chunk.transcript_id)
                text = chunk.text
                vector = chunk.embedding
                metadata = chunk.metadata_ or {}

            if vector is None:
                logger.debug("index_chunks: skipping chunk %s — no embedding", chunk_id)
                continue

            points.append(
                PointStruct(
                    id=chunk_id,
                    vector=vector,
                    payload={
                        "transcript_id": transcript_id,
                        "text": text,
                        "metadata": metadata,
                    },
                )
            )

        if not points:
            logger.info("index_chunks: no points to upsert")
            return

        self.client.upsert(
            collection_name=self.collection,
            points=points,
            wait=True,
        )
        logger.info("index_chunks: upserted %d points", len(points))

    async def ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not exist.

        Uses **Cosine** distance and 768-dimensional vectors matching
        nomic-embed-text-v2 output.
        """
        from qdrant_client.http.exceptions import UnexpectedResponse

        try:
            self.client.get_collection(self.collection)
            logger.info(
                "ensure_collection: collection %r already exists", self.collection
            )
        except UnexpectedResponse as exc:
            if exc.status_code == 404:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(
                        size=VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(
                    "ensure_collection: created collection %r (dim=%d, cosine)",
                    self.collection,
                    VECTOR_DIM,
                )
            else:
                raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(filters: dict[str, Any]) -> Filter:
        """Convert a plain-dict filter into a Qdrant ``Filter``.

        Supported keys: ``transcript_id``, ``project_id``, ``source_type``,
        ``date_from``, ``date_to``.

        Args:
            filters: Dictionary of filter criteria.

        Returns:
            A Qdrant ``Filter`` ready for ``client.search``.
        """
        must_conditions: list[Any] = []

        if transcript_id := filters.get("transcript_id"):
            must_conditions.append(
                FieldCondition(
                    key="transcript_id",
                    match=MatchValue(value=str(transcript_id)),
                )
            )

        if project_id := filters.get("project_id"):
            must_conditions.append(
                FieldCondition(
                    key="metadata.project_id",
                    match=MatchValue(value=str(project_id)),
                )
            )

        if source_type := filters.get("source_type"):
            must_conditions.append(
                FieldCondition(
                    key="metadata.source_type",
                    match=MatchValue(value=source_type),
                )
            )

        if date_from := filters.get("date_from"):
            must_conditions.append(
                FieldCondition(
                    key="metadata.created_at",
                    range=Range(gte=date_from.isoformat()),
                )
            )

        if date_to := filters.get("date_to"):
            must_conditions.append(
                FieldCondition(
                    key="metadata.created_at",
                    range=Range(lte=date_to.isoformat()),
                )
            )

        return Filter(must=must_conditions)
