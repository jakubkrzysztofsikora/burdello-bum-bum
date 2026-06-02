"""Tests for the semantic and hierarchical chunking pipeline.

Covers utterance splitting, semantic grouping by similarity,
max chunk size enforcement, and hierarchical tree construction.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.pipeline.chunking import HierarchicalChunker, SemanticChunker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_encoder():
    """Return a mock SentenceTransformer and patch chunking to use it."""
    mock_model = MagicMock()

    def mock_encode(texts, normalize_embeddings=True, **kwargs):
        """Return deterministic embeddings based on text content hash."""
        if isinstance(texts, str):
            texts = [texts]
        embeddings = []
        for text in texts:
            np.random.seed(hash(text) % 2**31)
            emb = np.random.randn(768).astype(np.float32)
            emb = emb / np.linalg.norm(emb)
            embeddings.append(emb)
        if len(embeddings) == 1:
            return embeddings[0]
        return np.stack(embeddings)

    mock_model.encode = mock_encode

    with patch("backend.pipeline.chunking.SentenceTransformer", return_value=mock_model):
        with patch.object(SemanticChunker, "__init__", lambda self, *a, **kw: setattr(self, "model", mock_model) or setattr(self, "threshold", 0.75) or setattr(self, "max_size", 512)):
            yield mock_model


@pytest.fixture
def sample_transcript() -> str:
    """Return a sample transcript with multiple speakers."""
    return (
        "User: Let's implement the authentication system.\n"
        "User: We need JWT tokens and a login endpoint.\n"
        "Assistant: I'll create the AuthService class with a login method.\n"
        "Assistant: The method will validate credentials and return a token.\n"
        "User: Great, also add password hashing with bcrypt.\n"
        "Assistant: bcrypt is already included in the dependencies.\n"
        "User: Now let's set up the database schema.\n"
        "Assistant: I'll create the users table with id, email, password_hash.\n"
    )


@pytest.fixture
def long_utterance() -> str:
    """Return an utterance longer than max_chunk_size."""
    return "Assistant: " + "x " * 600


# ---------------------------------------------------------------------------
# SemanticChunker.split_into_utterances
# ---------------------------------------------------------------------------


class TestSplitIntoUtterances:
    """Test speaker-based utterance splitting."""

    def test_splits_by_user_assistant(self, mock_encoder):
        """Should split transcript into User/Assistant utterances."""
        chunker = SemanticChunker()
        text = (
            "User: Hello there\n"
            "Assistant: Hi! How can I help?\n"
            "User: I need to fix a bug\n"
        )
        utterances = chunker.split_into_utterances(text)

        assert len(utterances) == 3
        assert all(u.startswith(("User:", "Assistant:")) for u in utterances)

    def test_splits_by_human_assistant(self, mock_encoder):
        """Should split on Human: prefix."""
        chunker = SemanticChunker()
        text = (
            "Human: What is the API rate limit?\n"
            "Assistant: It's 1000 requests per hour.\n"
        )
        utterances = chunker.split_into_utterances(text)

        assert len(utterances) == 2
        assert "Human:" in utterances[0]
        assert "Assistant:" in utterances[1]

    def test_splits_by_hash_prefix(self, mock_encoder):
        """Should split on ### prefix."""
        chunker = SemanticChunker()
        text = (
            "### Planning phase\n"
            "Let's design the data model.\n"
            "### Implementation\n"
            "Now let's write the code.\n"
        )
        utterances = chunker.split_into_utterances(text)

        assert len(utterances) == 2

    def test_splits_by_system_prefix(self, mock_encoder):
        """Should split on System: prefix."""
        chunker = SemanticChunker()
        text = (
            "System: Environment initialized\n"
            "User: Run the tests\n"
        )
        utterances = chunker.split_into_utterances(text)

        assert len(utterances) == 2
        assert "System:" in utterances[0]
        assert "User:" in utterances[1]

    def test_empty_text_returns_empty(self, mock_encoder):
        """Empty text should return empty list."""
        chunker = SemanticChunker()
        assert chunker.split_into_utterances("") == []
        assert chunker.split_into_utterances("   \n\n  ") == []

    def test_no_speaker_pattern_returns_single(self, mock_encoder):
        """Text without speaker prefixes returns as single utterance."""
        chunker = SemanticChunker()
        text = "This is just plain text without any speaker markers."
        utterances = chunker.split_into_utterances(text)

        assert len(utterances) == 1
        assert utterances[0] == text

    def test_preserves_utterance_content(self, mock_encoder):
        """Split utterances should preserve original content."""
        chunker = SemanticChunker()
        text = "User: Implement login\nAssistant: Done\n"
        utterances = chunker.split_into_utterances(text)

        assert "Implement login" in utterances[0]
        assert "Done" in utterances[1]


# ---------------------------------------------------------------------------
# SemanticChunker.create_chunks
# ---------------------------------------------------------------------------


class TestCreateChunks:
    """Test semantic chunk creation with similarity grouping."""

    def test_creates_chunks_from_transcript(self, mock_encoder, sample_transcript):
        """Should create multiple chunks from a transcript."""
        chunker = SemanticChunker()
        chunks = chunker.create_chunks(sample_transcript)

        assert isinstance(chunks, list)
        assert len(chunks) > 0

    def test_chunks_have_required_fields(self, mock_encoder, sample_transcript):
        """Each chunk must have text, start_idx, end_idx, metadata."""
        chunker = SemanticChunker()
        chunks = chunker.create_chunks(sample_transcript)

        for chunk in chunks:
            assert "text" in chunk
            assert "start_idx" in chunk
            assert "end_idx" in chunk
            assert "metadata" in chunk
            assert isinstance(chunk["text"], str)
            assert isinstance(chunk["start_idx"], int)
            assert isinstance(chunk["end_idx"], int)

    def test_chunk_text_not_empty(self, mock_encoder, sample_transcript):
        """Each chunk must contain non-empty text."""
        chunker = SemanticChunker()
        chunks = chunker.create_chunks(sample_transcript)

        for chunk in chunks:
            assert chunk["text"].strip()

    def test_chunks_cover_all_utterances(self, mock_encoder, sample_transcript):
        """Chunks should cover all utterance indices without gaps."""
        chunker = SemanticChunker()
        utterances = chunker.split_into_utterances(sample_transcript)
        chunks = chunker.create_chunks(sample_transcript)

        if len(utterances) > 0 and len(chunks) > 0:
            assert chunks[0]["start_idx"] == 0
            assert chunks[-1]["end_idx"] == len(utterances) - 1

    def test_respects_max_chunk_size(self, mock_encoder, long_utterance):
        """No chunk should exceed max_chunk_size characters."""
        chunker = SemanticChunker()
        chunker.max_size = 512
        chunks = chunker.create_chunks(long_utterance)

        for chunk in chunks:
            assert len(chunk["text"]) <= 512 + 50  # Allow small margin for speaker prefix

    def test_empty_transcript_returns_empty(self, mock_encoder):
        """Empty transcript should return empty chunks list."""
        chunker = SemanticChunker()
        assert chunker.create_chunks("") == []

    def test_metadata_attached(self, mock_encoder, sample_transcript):
        """Custom metadata should be attached to chunks."""
        chunker = SemanticChunker()
        meta = {"transcript_id": str(uuid.uuid4()), "source": "test"}
        chunks = chunker.create_chunks(sample_transcript, metadata=meta)

        for chunk in chunks:
            assert "source" in chunk["metadata"]
            assert chunk["metadata"]["source"] == "test"

    def test_utterance_count_in_metadata(self, mock_encoder, sample_transcript):
        """Metadata should include utterance count per chunk."""
        chunker = SemanticChunker()
        chunks = chunker.create_chunks(sample_transcript)

        for chunk in chunks:
            assert "utterance_count" in chunk["metadata"]
            assert chunk["metadata"]["utterance_count"] > 0


# ---------------------------------------------------------------------------
# HierarchicalChunker
# ---------------------------------------------------------------------------


class TestHierarchicalChunker:
    """Test hierarchical tree construction."""

    def test_creates_tree_structure(self, mock_encoder, sample_transcript):
        """Should produce a nested tree with session -> topic -> utterance."""
        chunker = HierarchicalChunker()
        tree = chunker.chunk_transcript(sample_transcript)

        assert tree["level"] == "session"
        assert "text" in tree
        assert "children" in tree
        assert "metadata" in tree

    def test_topic_nodes_have_utterance_children(self, mock_encoder, sample_transcript):
        """Topic nodes should contain utterance-level children."""
        chunker = HierarchicalChunker()
        tree = chunker.chunk_transcript(sample_transcript)

        for topic in tree["children"]:
            assert topic["level"] == "topic"
            assert "children" in topic
            assert len(topic["children"]) > 0
            for utterance in topic["children"]:
                assert utterance["level"] == "utterance"
                assert "text" in utterance

    def test_empty_transcript_returns_session_node(self, mock_encoder):
        """Empty transcript should still return a session-level node."""
        chunker = HierarchicalChunker()
        tree = chunker.chunk_transcript("")

        assert tree["level"] == "session"
        assert tree["children"] == []

    def test_session_metadata_preserved(self, mock_encoder, sample_transcript):
        """Session metadata should be preserved in the root node."""
        chunker = HierarchicalChunker()
        meta = {"session_id": "test-123", "user": "alice"}
        tree = chunker.chunk_transcript(sample_transcript, session_metadata=meta)

        assert tree["metadata"]["session_id"] == "test-123"
        assert tree["metadata"]["user"] == "alice"

    def test_topics_have_text_and_indices(self, mock_encoder, sample_transcript):
        """Topic nodes should include text and index range."""
        chunker = HierarchicalChunker()
        tree = chunker.chunk_transcript(sample_transcript)

        for topic in tree["children"]:
            assert "text" in topic
            assert "start_idx" in topic
            assert "end_idx" in topic
            assert topic["start_idx"] <= topic["end_idx"]
