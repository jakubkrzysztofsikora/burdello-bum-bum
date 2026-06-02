"""Tests for transcript normalization.

Covers conversion from ExtractedTranscript to DB-ready schemas,
message normalisation, and edge cases.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import pytest

from backend.core.schemas import MessageCreate, TranscriptCreate
from backend.pipeline.normalization import TranscriptNormalizer
from backend.skills.base import ExtractedTranscript, NormalizedMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def normalizer() -> TranscriptNormalizer:
    """Return a TranscriptNormalizer instance."""
    return TranscriptNormalizer()


@pytest.fixture
def sample_source_id() -> uuid.UUID:
    """Return a deterministic source UUID."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def sample_extracted() -> ExtractedTranscript:
    """Return a sample ExtractedTranscript with messages."""
    return ExtractedTranscript(
        source_type="claude_code",
        title="Auth Implementation Session",
        raw_text="User: Let's build auth\nAssistant: I'll create the login endpoint.",
        language="en",
        messages=[
            NormalizedMessage(
                speaker="user",
                content="Let's build auth",
                sequence=0,
            ),
            NormalizedMessage(
                speaker="assistant",
                content="I'll create the login endpoint.",
                sequence=1,
            ),
        ],
        metadata={"session_id": "sess-001"},
    )


# ---------------------------------------------------------------------------
# TranscriptNormalizer.normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    """Test the main normalize method."""

    def test_returns_dict_with_transcript_and_messages(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Should return dict with 'transcript' and 'messages' keys."""
        result = normalizer.normalize(sample_extracted, sample_source_id)

        assert "transcript" in result
        assert "messages" in result

    def test_transcript_is_transcript_create(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """'transcript' value should be a TranscriptCreate instance."""
        result = normalizer.normalize(sample_extracted, sample_source_id)

        assert isinstance(result["transcript"], TranscriptCreate)

    def test_messages_is_list_of_message_create(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """'messages' value should be a list of MessageCreate instances."""
        result = normalizer.normalize(sample_extracted, sample_source_id)

        assert isinstance(result["messages"], list)
        assert len(result["messages"]) == 2
        for msg in result["messages"]:
            assert isinstance(msg, MessageCreate)

    def test_transcript_has_correct_source_id(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript should reference the correct source_id."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.source_id == sample_source_id

    def test_transcript_has_title(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript should preserve the title."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.title == "Auth Implementation Session"

    def test_transcript_has_raw_text(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript should preserve raw_text."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.raw_text == sample_extracted.raw_text

    def test_transcript_has_language(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript should preserve language."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.language == "en"

    def test_transcript_metadata_contains_source_type(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript metadata should include source_type."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.metadata is not None
        assert transcript.metadata["source_type"] == "claude_code"

    def test_transcript_metadata_merges_extra(
        self,
        normalizer: TranscriptNormalizer,
        sample_extracted: ExtractedTranscript,
        sample_source_id: uuid.UUID,
    ):
        """Transcript metadata should merge extracted metadata."""
        result = normalizer.normalize(sample_extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.metadata is not None
        assert transcript.metadata["session_id"] == "sess-001"

    def test_generates_default_title_when_none(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Should generate a default title when extracted title is None."""
        extracted = ExtractedTranscript(
            source_type="codex",
            title=None,
            raw_text="Some text",
            messages=[],
        )
        result = normalizer.normalize(extracted, sample_source_id)
        transcript: TranscriptCreate = result["transcript"]

        assert transcript.title == "Session from codex"

    def test_empty_messages_returns_empty_list(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """ExtractedTranscript with no messages should produce empty messages list."""
        extracted = ExtractedTranscript(
            source_type="vibe",
            raw_text="No messages here",
            messages=[],
        )
        result = normalizer.normalize(extracted, sample_source_id)

        assert result["messages"] == []

    def test_single_message_normalized(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """A single message should be correctly normalized."""
        extracted = ExtractedTranscript(
            source_type="agy",
            messages=[
                NormalizedMessage(
                    speaker="user",
                    content="Hello AI",
                    sequence=0,
                ),
            ],
        )
        result = normalizer.normalize(extracted, sample_source_id)

        assert len(result["messages"]) == 1
        msg: MessageCreate = result["messages"][0]
        assert msg.speaker == "user"
        assert msg.content == "Hello AI"
        assert msg.sequence == 0


# ---------------------------------------------------------------------------
# TranscriptNormalizer._normalize_message
# ---------------------------------------------------------------------------


class TestNormalizeMessage:
    """Test individual message normalisation."""

    def test_string_content_preserved(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """String content should be preserved as-is."""
        msg = NormalizedMessage(speaker="user", content="Hello", sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.content == "Hello"

    def test_list_content_serialised_to_json(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """List content should be serialised to a JSON string."""
        content = [{"type": "text", "value": "Hello"}, {"type": "tool_use", "name": "search"}]
        msg = NormalizedMessage(speaker="assistant", content=content, sequence=1)
        result = normalizer._normalize_message(msg, sample_source_id, 1)

        assert isinstance(result.content, str)
        parsed = json.loads(result.content)
        assert parsed == content

    def test_dict_content_serialised_to_json(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Dict content should be serialised to a JSON string."""
        content = {"tool": "calculator", "input": "2+2"}
        msg = NormalizedMessage(speaker="assistant", content=content, sequence=2)
        result = normalizer._normalize_message(msg, sample_source_id, 2)

        assert isinstance(result.content, str)
        parsed = json.loads(result.content)
        assert parsed == content

    def test_none_speaker_defaults_to_unknown(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """None speaker should be normalised to 'unknown'."""
        msg = NormalizedMessage(speaker=None, content="Hello", sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.speaker == "unknown"

    def test_sequence_set_from_index(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Sequence should be set from the index parameter."""
        msg = NormalizedMessage(content="Test", sequence=99)
        result = normalizer._normalize_message(msg, sample_source_id, 5)

        assert result.sequence == 5

    def test_timestamp_converted_to_seconds(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Timestamp should be converted to Unix seconds."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        msg = NormalizedMessage(
            content="Test",
            timestamp=ts,
            sequence=0,
        )
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.timestamp_seconds == ts.timestamp()

    def test_none_timestamp_has_none_seconds(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """None timestamp should produce None timestamp_seconds."""
        msg = NormalizedMessage(content="Test", timestamp=None, sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.timestamp_seconds is None

    def test_metadata_contains_transcript_id(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Message metadata should contain the transcript_id."""
        msg = NormalizedMessage(content="Test", sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.metadata is not None
        assert result.metadata["transcript_id"] == str(sample_source_id)

    def test_metadata_merges_extra(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Message metadata should merge msg.metadata."""
        msg = NormalizedMessage(
            content="Test",
            sequence=0,
            metadata={"tool_call_id": "call_123"},
        )
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.metadata is not None
        assert result.metadata["tool_call_id"] == "call_123"

    def test_numeric_content_converted_to_string(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Non-string, non-list/dict content should be converted to string."""
        msg = NormalizedMessage(content=42, sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        assert result.content == "42"

    def test_complex_nested_list_content(
        self,
        normalizer: TranscriptNormalizer,
        sample_source_id: uuid.UUID,
    ):
        """Complex nested list content should be serialised correctly."""
        content = [
            {"type": "text", "text": "Let me search"},
            {
                "type": "tool_use",
                "id": "tool_1",
                "name": "search",
                "input": {"query": "auth best practices"},
            },
            {
                "type": "tool_result",
                "tool_use_id": "tool_1",
                "content": [{"type": "text", "text": "Results: ..."}],
            },
        ]
        msg = NormalizedMessage(speaker="assistant", content=content, sequence=0)
        result = normalizer._normalize_message(msg, sample_source_id, 0)

        parsed = json.loads(result.content)
        assert len(parsed) == 3
        assert parsed[1]["type"] == "tool_use"
