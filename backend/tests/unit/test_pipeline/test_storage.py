"""Tests for the pipeline storage layer.

Covers source storage, transcript storage, chunk storage with Qdrant
upsert, transcript status updates, source existence checks, and
transcript text retrieval.  All external services are mocked.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.schemas import MessageCreate, TranscriptCreate
from backend.pipeline.storage import PipelineStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session():
    """Return a mocked AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_search_engine():
    """Return a mocked HybridSearchEngine."""
    engine = AsyncMock()
    engine.index_chunks = AsyncMock()
    return engine


@pytest.fixture
def storage(mock_db_session, mock_search_engine):
    """Return a PipelineStorage instance with mocked dependencies."""
    return PipelineStorage(db=mock_db_session, search_engine=mock_search_engine)


@pytest.fixture
def sample_transcript_data() -> dict[str, Any]:
    """Return sample normalized transcript data."""
    return {
        "transcript": TranscriptCreate(
            source_id=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
            title="Test Session",
            raw_text="User: Hello\nAssistant: Hi!",
            language="en",
            metadata={"source_type": "claude_code"},
        ),
        "messages": [
            MessageCreate(speaker="user", content="Hello", sequence=0),
            MessageCreate(speaker="assistant", content="Hi!", sequence=1),
        ],
    }


# ---------------------------------------------------------------------------
# store_source
# ---------------------------------------------------------------------------


class TestStoreSource:
    """Test source storage."""

    @pytest.mark.asyncio
    async def test_creates_source(self, storage, mock_db_session):
        """Should create a Source and add it to the session."""
        source_id = await storage.store_source(
            path="/home/user/.claude/projects/test.jsonl",
            file_hash="abc123",
            provider="claude_code",
            size=1024,
        )

        assert isinstance(source_id, uuid.UUID)
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_source_has_correct_metadata(self, storage, mock_db_session):
        """Source metadata should contain file info."""
        await storage.store_source(
            path="/home/user/.claude/projects/test.jsonl",
            file_hash="abc123",
            provider="claude_code",
            size=1024,
        )

        call_args = mock_db_session.add.call_args[0][0]
        assert call_args.metadata_["file_hash"] == "abc123"
        assert call_args.metadata_["file_size"] == 1024
        assert call_args.metadata_["provider"] == "claude_code"

    @pytest.mark.asyncio
    async def test_source_title_from_filename(self, storage, mock_db_session):
        """Source title should be derived from filename."""
        await storage.store_source(
            path="/home/user/.claude/projects/test.jsonl",
            file_hash="abc123",
            provider="claude_code",
            size=1024,
        )

        call_args = mock_db_session.add.call_args[0][0]
        assert call_args.title == "test.jsonl"


# ---------------------------------------------------------------------------
# store_transcript
# ---------------------------------------------------------------------------


class TestStoreTranscript:
    """Test transcript and message storage."""

    @pytest.mark.asyncio
    async def test_creates_transcript(self, storage, mock_db_session, sample_transcript_data):
        """Should create a Transcript and add it to the session."""
        source_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        transcript_id = await storage.store_transcript(source_id, sample_transcript_data)

        assert isinstance(transcript_id, uuid.UUID)
        assert mock_db_session.add.call_count == 3  # transcript + 2 messages

    @pytest.mark.asyncio
    async def test_transcript_status_is_processing(self, storage, mock_db_session, sample_transcript_data):
        """New transcript should have 'processing' status."""
        source_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        await storage.store_transcript(source_id, sample_transcript_data)

        # First add call is the Transcript
        call_args = mock_db_session.add.call_args_list[0][0][0]
        assert call_args.status == "processing"

    @pytest.mark.asyncio
    async def test_messages_have_correct_sequence(self, storage, mock_db_session, sample_transcript_data):
        """Messages should have correct sequence numbers."""
        source_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        await storage.store_transcript(source_id, sample_transcript_data)

        # Second and third add calls are Messages
        msg1 = mock_db_session.add.call_args_list[1][0][0]
        msg2 = mock_db_session.add.call_args_list[2][0][0]
        assert msg1.sequence == 0
        assert msg2.sequence == 1

    @pytest.mark.asyncio
    async def test_empty_messages(self, storage, mock_db_session):
        """Transcript with no messages should not add message rows."""
        source_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        data = {
            "transcript": TranscriptCreate(
                source_id=source_id,
                title="Empty Session",
                raw_text="No messages",
            ),
            "messages": [],
        }
        await storage.store_transcript(source_id, data)

        # Only 1 add call (the transcript)
        assert mock_db_session.add.call_count == 1


# ---------------------------------------------------------------------------
# store_chunks
# ---------------------------------------------------------------------------


class TestStoreChunks:
    """Test chunk storage to PostgreSQL and Qdrant."""

    @pytest.mark.asyncio
    async def test_stores_chunks_in_db(self, storage, mock_db_session):
        """Should add chunk records to the database session."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        chunks = [
            {"text": "Chunk 1", "embedding": [0.1] * 768, "metadata": {"idx": 0}},
            {"text": "Chunk 2", "embedding": [0.2] * 768, "metadata": {"idx": 1}},
        ]
        chunk_ids = await storage.store_chunks(transcript_id, chunks)

        assert len(chunk_ids) == 2
        assert mock_db_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_chunk_ids(self, storage, mock_db_session):
        """Should return a list of UUIDs for the stored chunks."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        chunks = [{"text": "Chunk 1", "embedding": [0.1] * 768}]
        chunk_ids = await storage.store_chunks(transcript_id, chunks)

        assert all(isinstance(cid, uuid.UUID) for cid in chunk_ids)

    @pytest.mark.asyncio
    async def test_upserts_to_qdrant(self, storage, mock_search_engine):
        """Should call search_engine.index_chunks for Qdrant upsert."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        chunks = [
            {"text": "Chunk 1", "embedding": [0.1] * 768, "metadata": {}},
        ]
        await storage.store_chunks(transcript_id, chunks)

        mock_search_engine.index_chunks.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_empty(self, storage, mock_db_session):
        """Empty chunks list should return empty list."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        chunk_ids = await storage.store_chunks(transcript_id, [])

        assert chunk_ids == []
        mock_db_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_qdrant_on_none_search_engine(self, mock_db_session):
        """Should not call Qdrant when search_engine is None."""
        storage_no_search = PipelineStorage(db=mock_db_session, search_engine=None)
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        chunks = [{"text": "Chunk 1", "embedding": [0.1] * 768}]

        chunk_ids = await storage_no_search.store_chunks(transcript_id, chunks)

        assert len(chunk_ids) == 1
        # No exception raised


# ---------------------------------------------------------------------------
# update_transcript_status
# ---------------------------------------------------------------------------


class TestUpdateTranscriptStatus:
    """Test transcript status updates."""

    @pytest.mark.asyncio
    async def test_updates_status(self, storage, mock_db_session):
        """Should update the transcript status field."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        # Mock the scalar result
        mock_transcript = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_transcript
        mock_db_session.execute.return_value = mock_result

        await storage.update_transcript_status(transcript_id, "completed")

        assert mock_transcript.status == "completed"

    @pytest.mark.asyncio
    async def test_noop_on_missing_transcript(self, storage, mock_db_session):
        """Should not error if transcript doesn't exist."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Should not raise
        await storage.update_transcript_status(transcript_id, "completed")


# ---------------------------------------------------------------------------
# source_exists
# ---------------------------------------------------------------------------


class TestSourceExists:
    """Test source existence check by file hash."""

    @pytest.mark.asyncio
    async def test_returns_true_when_source_exists(self, storage, mock_db_session):
        """Should return True when a source with the hash exists."""
        mock_source = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_db_session.execute.return_value = mock_result

        exists = await storage.source_exists("hash123")

        assert exists is True

    @pytest.mark.asyncio
    async def test_returns_false_when_source_missing(self, storage, mock_db_session):
        """Should return False when no source matches the hash."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        exists = await storage.source_exists("nonexistent")

        assert exists is False


# ---------------------------------------------------------------------------
# get_transcript_text
# ---------------------------------------------------------------------------


class TestGetTranscriptText:
    """Test transcript text retrieval."""

    @pytest.mark.asyncio
    async def test_returns_raw_text_when_available(self, storage, mock_db_session):
        """Should return raw_text when it exists on the transcript."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        mock_transcript = MagicMock()
        mock_transcript.raw_text = "This is the raw text"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_transcript
        mock_db_session.execute.return_value = mock_result

        text = await storage.get_transcript_text(transcript_id)

        assert text == "This is the raw text"

    @pytest.mark.asyncio
    async def test_returns_empty_when_transcript_missing(self, storage, mock_db_session):
        """Should return empty string when transcript doesn't exist."""
        transcript_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        text = await storage.get_transcript_text(transcript_id)

        assert text == ""
