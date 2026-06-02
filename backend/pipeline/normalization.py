"""Transcript normalisation: converts skill output to DB-ready schemas.

Provides ``TranscriptNormalizer`` which transforms an ``ExtractedTranscript``
(produced by a provider-specific skill) into ``TranscriptCreate`` and
``MessageCreate`` Pydantic schemas ready for database insertion.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from backend.core.schemas import MessageCreate, TranscriptCreate
from backend.skills.base import ExtractedTranscript, NormalizedMessage

logger = logging.getLogger(__name__)


class TranscriptNormalizer:
    """Converts ``ExtractedTranscript`` into DB-ready Pydantic schemas."""

    def normalize(
        self,
        extracted: ExtractedTranscript,
        source_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Normalise an extracted transcript into DB-ready objects.

        Args:
            extracted: The skill-extracted transcript data.
            source_id: UUID of the parent ``Source`` record.

        Returns:
            Dictionary with keys ``transcript`` (TranscriptCreate) and
            ``messages`` (list of MessageCreate).
        """
        transcript_create = TranscriptCreate(
            source_id=source_id,
            title=extracted.title or f"Session from {extracted.source_type}",
            raw_text=extracted.raw_text,
            language=extracted.language or "en",
            metadata={
                "source_type": extracted.source_type,
                **extracted.metadata,
            },
        )

        message_creates: list[MessageCreate] = []
        for idx, msg in enumerate(extracted.messages):
            message_creates.append(
                self._normalize_message(msg, transcript_id=source_id, index=idx)
            )

        return {
            "transcript": transcript_create,
            "messages": message_creates,
        }

    def _normalize_message(
        self,
        msg: NormalizedMessage,
        transcript_id: uuid.UUID,
        index: int,
    ) -> MessageCreate:
        """Convert a single ``NormalizedMessage`` into a ``MessageCreate``.

        Handles content as either a plain string or a list of content blocks
        (e.g. tool-use JSON).  In the latter case the content is serialised
        to a JSON string.

        Args:
            msg: The normalised message from the skill.
            transcript_id: UUID of the parent transcript (used as placeholder).
            index: Zero-based sequence index.

        Returns:
            A ``MessageCreate`` schema instance.
        """
        # Resolve content — serialise list/dict to JSON string
        if isinstance(msg.content, list):
            content_str = json.dumps(msg.content, ensure_ascii=False)
        elif isinstance(msg.content, dict):
            content_str = json.dumps(msg.content, ensure_ascii=False)
        else:
            content_str = str(msg.content)

        # Resolve speaker
        speaker = msg.speaker or "unknown"

        # Build timestamp_seconds if a datetime is available
        timestamp_seconds: float | None = None
        if msg.timestamp is not None:
            timestamp_seconds = msg.timestamp.timestamp()

        return MessageCreate(
            speaker=speaker,
            content=content_str,
            timestamp_seconds=timestamp_seconds,
            sequence=index,
            metadata={
                "transcript_id": str(transcript_id),
                **msg.metadata,
            },
        )
