"""Semantic and hierarchical chunking for transcript text.

Provides ``SemanticChunker`` which groups utterances by embedding similarity,
and ``HierarchicalChunker`` which builds a tree structure of
session -> topics -> utterances.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Speaker prefixes used to split transcripts into utterances
SPEAKER_PATTERNS = [
    r"\n\s*User\s*:\s*",
    r"\n\s*Assistant\s*:\s*",
    r"\n\s*Human\s*:\s*",
    r"\n\s*###\s*",
    r"\n\s*System\s*:\s*",
    r"\n\s*AI\s*:\s*",
]

# Combined regex for splitting
_UTTERANCE_SPLIT_RE = re.compile(
    f"({'|'.join(SPEAKER_PATTERNS)})",
    re.IGNORECASE,
)

# Extract the speaker label from a prefix match
_SPEAKER_LABEL_RE = re.compile(r"(User|Assistant|Human|System|AI)", re.IGNORECASE)


class SemanticChunker:
    """Chunks transcript text by semantic similarity of utterances.

    Splits the transcript into individual utterances (by speaker prefix),
    embeds each utterance, and groups consecutive utterances whose cosine
    similarity exceeds *similarity_threshold*.  Respects *max_chunk_size*
    as a hard character limit.
    """

    def __init__(
        self,
        model_name: str | None = None,
        similarity_threshold: float = 0.75,
        max_chunk_size: int = 512,
    ) -> None:
        """Initialise the semantic chunker.

        Args:
            model_name: Sentence-transformers model name. Falls back to
                ``BB_EMBEDDING_MODEL`` from settings.
            similarity_threshold: Minimum cosine similarity to group
                consecutive utterances into the same chunk.
            max_chunk_size: Maximum chunk length in characters.
        """
        settings = get_settings()
        resolved_model = model_name or settings.BB_EMBEDDING_MODEL

        # Shared per-process model (chunker + embedder reuse one instance).
        from backend.pipeline.model_cache import get_sentence_transformer

        self.model = get_sentence_transformer(resolved_model)
        self.threshold = similarity_threshold
        self.max_size = max_chunk_size or settings.BB_CHUNK_SIZE

    def split_into_utterances(self, text: str) -> list[str]:
        """Split transcript text into speaker-delimited utterances.

        Splits on patterns like ``User:``, ``Assistant:``, ``Human:``,
        ``###``, ``System:``, ``AI:``.

        Args:
            text: Raw transcript text.

        Returns:
            List of utterance strings (speaker prefix + content).
        """
        if not text or not text.strip():
            return []

        # Normalise line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Split while keeping delimiters
        parts = _UTTERANCE_SPLIT_RE.split(text)

        utterances: list[str] = []
        current_speaker: str | None = None

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check if this part is a speaker delimiter
            if _UTTERANCE_SPLIT_RE.fullmatch(f"\n{part}") or any(
                re.match(p.strip("\\n\\s*") + r"$", part, re.IGNORECASE)
                for p in SPEAKER_PATTERNS
            ):
                speaker_match = _SPEAKER_LABEL_RE.search(part)
                current_speaker = speaker_match.group(1).capitalize() if speaker_match else "Unknown"
                continue

            # Content part — prepend speaker label if we have one
            if current_speaker:
                utterances.append(f"{current_speaker}: {part}")
            else:
                utterances.append(part)

        # If no speaker patterns were found, treat the whole text as one chunk
        if not utterances and text.strip():
            return [text.strip()]

        return utterances

    def create_chunks(
        self,
        transcript: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Create semantically-grouped chunks from transcript text.

        1. Split into utterances.
        2. Embed each utterance.
        3. Group consecutive utterances by similarity threshold.
        4. Respect max_chunk_size.

        Args:
            transcript: Full transcript text.
            metadata: Optional metadata to attach to each chunk.

        Returns:
            List of chunk dicts with ``text``, ``start_idx``, ``end_idx``,
            and ``metadata`` keys.
        """
        utterances = self.split_into_utterances(transcript)
        if not utterances:
            return []

        # Embed all utterances
        embeddings = self.model.encode(utterances, normalize_embeddings=True)

        chunks: list[dict[str, Any]] = []
        current_texts: list[str] = []
        current_start = 0

        for i, (utterance, embedding) in enumerate(zip(utterances, embeddings)):
            # Decide whether to start a new chunk
            start_new_chunk = False

            if not current_texts:
                start_new_chunk = True
            elif len("\n".join(current_texts + [utterance])) > self.max_size:
                start_new_chunk = True
            elif i > 0:
                # Compare similarity with the previous utterance
                prev_embedding = embeddings[i - 1]
                similarity = float(
                    np.dot(embedding, prev_embedding)
                    / (np.linalg.norm(embedding) * np.linalg.norm(prev_embedding) + 1e-10)
                )
                if similarity < self.threshold:
                    start_new_chunk = True

            if start_new_chunk and current_texts:
                chunks.append(
                    {
                        "text": "\n".join(current_texts),
                        "start_idx": current_start,
                        "end_idx": i - 1,
                        "metadata": {**(metadata or {}), "utterance_count": len(current_texts)},
                    }
                )
                current_texts = [utterance]
                current_start = i
            else:
                current_texts.append(utterance)

        # Flush remaining
        if current_texts:
            chunks.append(
                {
                    "text": "\n".join(current_texts),
                    "start_idx": current_start,
                    "end_idx": len(utterances) - 1,
                    "metadata": {**(metadata or {}), "utterance_count": len(current_texts)},
                }
            )

        logger.info(
            "create_chunks: %d utterances -> %d chunks",
            len(utterances),
            len(chunks),
        )
        return chunks


class HierarchicalChunker:
    """Creates a hierarchical tree: session -> topics -> utterances.

    Uses ``SemanticChunker`` to first group utterances, then builds a
    nested tree structure suitable for multi-level retrieval.
    """

    def __init__(self, semantic_chunker: SemanticChunker | None = None) -> None:
        """Initialise the hierarchical chunker.

        Args:
            semantic_chunker: An existing ``SemanticChunker`` instance.
                A new one is created if not provided.
        """
        self.semantic = semantic_chunker or SemanticChunker()

    def chunk_transcript(
        self,
        transcript: str,
        session_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a hierarchical chunk tree from a transcript.

        Args:
            transcript: Full transcript text.
            session_metadata: Optional metadata for the root session node.

        Returns:
            A nested dict with levels ``session``, ``topic``, ``utterance``.
        """
        utterances = self.semantic.split_into_utterances(transcript)
        if not utterances:
            return {
                "level": "session",
                "text": transcript,
                "metadata": session_metadata or {},
                "children": [],
            }

        # Embed for semantic grouping at topic level
        embeddings = self.semantic.model.encode(utterances, normalize_embeddings=True)

        topic_groups: list[dict[str, Any]] = []
        current_topic_utterances: list[str] = []
        current_topic_children: list[dict[str, Any]] = []
        current_topic_start = 0

        for i, (utterance, embedding) in enumerate(zip(utterances, embeddings)):
            start_new_topic = False

            if not current_topic_utterances:
                start_new_topic = True
            elif i > 0:
                prev_embedding = embeddings[i - 1]
                similarity = float(
                    np.dot(embedding, prev_embedding)
                    / (np.linalg.norm(embedding) * np.linalg.norm(prev_embedding) + 1e-10)
                )
                if similarity < self.semantic.threshold:
                    start_new_topic = True

            if start_new_topic and current_topic_utterances:
                topic_groups.append(
                    {
                        "level": "topic",
                        "text": "\n".join(current_topic_utterances),
                        "start_idx": current_topic_start,
                        "end_idx": i - 1,
                        "children": current_topic_children,
                    }
                )
                current_topic_utterances = [utterance]
                current_topic_children = [
                    {"level": "utterance", "text": utterance, "index": i}
                ]
                current_topic_start = i
            else:
                current_topic_utterances.append(utterance)
                current_topic_children.append(
                    {"level": "utterance", "text": utterance, "index": i}
                )

        # Flush last topic
        if current_topic_utterances:
            topic_groups.append(
                {
                    "level": "topic",
                    "text": "\n".join(current_topic_utterances),
                    "start_idx": current_topic_start,
                    "end_idx": len(utterances) - 1,
                    "children": current_topic_children,
                }
            )

        return {
            "level": "session",
            "text": transcript,
            "metadata": session_metadata or {},
            "children": topic_groups,
        }
