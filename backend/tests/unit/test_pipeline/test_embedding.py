"""Tests for the embedding generation pipeline.

Covers single-text embedding, batch embedding, chunk embedding,
and dimension verification with mocked SentenceTransformer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.pipeline.embedding import EmbeddingEngine, get_embedding_engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sentence_transformer():
    """Patch SentenceTransformer with a deterministic mock."""
    mock_model = MagicMock()

    def mock_encode(texts, normalize_embeddings=True, **kwargs):
        """Return deterministic 768-dim embeddings."""
        single_input = isinstance(texts, str)
        if single_input:
            texts = [texts]

        embeddings = []
        for text in texts:
            np.random.seed(hash(text) % 2**31)
            emb = np.random.randn(768).astype(np.float32)
            if normalize_embeddings:
                emb = emb / np.linalg.norm(emb)
            embeddings.append(emb)

        if single_input:
            return embeddings[0]
        if kwargs.get("convert_to_numpy", False):
            return np.stack(embeddings)
        return embeddings

    mock_model.encode = mock_encode

    with patch(
        "backend.pipeline.embedding.SentenceTransformer",
        return_value=mock_model,
    ):
        yield mock_model


@pytest.fixture
def embedding_engine(mock_sentence_transformer) -> EmbeddingEngine:
    """Return an EmbeddingEngine with mocked transformer."""
    return EmbeddingEngine(model_name="mock-model")


# ---------------------------------------------------------------------------
# EmbeddingEngine.embed
# ---------------------------------------------------------------------------


class TestEmbed:
    """Test single-text embedding."""

    def test_returns_list_of_floats(self, embedding_engine):
        """Should return a list of floats."""
        result = embedding_engine.embed("Hello world")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_dimension_is_768(self, embedding_engine):
        """Embedding should have exactly 768 dimensions."""
        result = embedding_engine.embed("Hello world")

        assert len(result) == 768

    def test_empty_text_returns_zero_vector(self, embedding_engine):
        """Empty text should return a zero vector."""
        result = embedding_engine.embed("")

        assert len(result) == 768
        assert all(v == 0.0 for v in result)

    def test_whitespace_only_returns_zero_vector(self, embedding_engine):
        """Whitespace-only text should return a zero vector."""
        result = embedding_engine.embed("   \n\t  ")

        assert all(v == 0.0 for v in result)

    def test_different_texts_different_embeddings(self, embedding_engine):
        """Different inputs should produce different embeddings."""
        emb1 = embedding_engine.embed("Hello world")
        emb2 = embedding_engine.embed("Goodbye world")

        assert emb1 != emb2

    def test_same_text_same_embedding(self, embedding_engine):
        """Same input should produce identical embeddings."""
        emb1 = embedding_engine.embed("Test text")
        emb2 = embedding_engine.embed("Test text")

        assert emb1 == emb2

    def test_normalised_embeddings(self, embedding_engine):
        """Embeddings should be L2-normalised (unit length)."""
        result = embedding_engine.embed("Some text here")
        vec = np.array(result)
        norm = np.linalg.norm(vec)

        assert abs(norm - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# EmbeddingEngine.embed_batch
# ---------------------------------------------------------------------------


class TestEmbedBatch:
    """Test batch embedding."""

    def test_returns_list_of_lists(self, embedding_engine):
        """Should return a list of embedding vectors."""
        texts = ["Hello", "World", "Test"]
        result = embedding_engine.embed_batch(texts)

        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_embedding_is_768_dim(self, embedding_engine):
        """Each embedding should have 768 dimensions."""
        texts = ["Hello", "World"]
        result = embedding_engine.embed_batch(texts)

        for emb in result:
            assert len(emb) == 768
            assert all(isinstance(v, float) for v in emb)

    def test_empty_list_returns_empty(self, embedding_engine):
        """Empty input list should return empty list."""
        assert embedding_engine.embed_batch([]) == []

    def test_handles_empty_strings_in_batch(self, embedding_engine):
        """Batch with empty strings should return zero vectors for them."""
        texts = ["Hello", "", "World"]
        result = embedding_engine.embed_batch(texts)

        assert len(result) == 3
        assert all(v == 0.0 for v in result[1])

    def test_all_empty_strings_returns_zero_vectors(self, embedding_engine):
        """All-empty batch should return all zero vectors."""
        texts = ["", "  ", "\n"]
        result = embedding_engine.embed_batch(texts)

        assert len(result) == 3
        for emb in result:
            assert all(v == 0.0 for v in emb)

    def test_embeddings_correspond_to_inputs(self, embedding_engine):
        """Each output should correspond to its input text."""
        texts = ["First text", "Second text"]
        result = embedding_engine.embed_batch(texts)

        # Same text should give same embedding whether batched or single
        assert result[0] == embedding_engine.embed("First text")
        assert result[1] == embedding_engine.embed("Second text")


# ---------------------------------------------------------------------------
# EmbeddingEngine.embed_chunks
# ---------------------------------------------------------------------------


class TestEmbedChunks:
    """Test embedding chunks dicts."""

    def test_adds_embedding_field(self, embedding_engine):
        """Should add 'embedding' key to each chunk dict."""
        chunks = [
            {"text": "First chunk"},
            {"text": "Second chunk"},
        ]
        result = embedding_engine.embed_chunks(chunks)

        for chunk in result:
            assert "embedding" in chunk
            assert isinstance(chunk["embedding"], list)
            assert len(chunk["embedding"]) == 768

    def test_empty_chunks_returns_empty(self, embedding_engine):
        """Empty chunks list should return empty list."""
        assert embedding_engine.embed_chunks([]) == []

    def test_preserves_existing_keys(self, embedding_engine):
        """Should preserve existing chunk dict keys."""
        chunks = [
            {"text": "Chunk", "metadata": {"idx": 0}, "extra": "value"},
        ]
        result = embedding_engine.embed_chunks(chunks)

        assert result[0]["text"] == "Chunk"
        assert result[0]["metadata"] == {"idx": 0}
        assert result[0]["extra"] == "value"
        assert "embedding" in result[0]

    def test_chunks_with_empty_text(self, embedding_engine):
        """Chunks with empty text should get zero vectors."""
        chunks = [
            {"text": "Valid chunk"},
            {"text": ""},
        ]
        result = embedding_engine.embed_chunks(chunks)

        assert len(result[1]["embedding"]) == 768
        assert all(v == 0.0 for v in result[1]["embedding"])

    def test_returns_same_list_object(self, embedding_engine):
        """embed_chunks should modify the list in place and return it."""
        chunks = [{"text": "Chunk"}]
        result = embedding_engine.embed_chunks(chunks)

        assert result is chunks
        assert "embedding" in chunks[0]


# ---------------------------------------------------------------------------
# get_embedding_engine singleton
# ---------------------------------------------------------------------------


class TestGetEmbeddingEngine:
    """Test the singleton factory."""

    def test_returns_embedding_engine(self, mock_sentence_transformer):
        """Should return an EmbeddingEngine instance."""
        engine = get_embedding_engine()

        assert isinstance(engine, EmbeddingEngine)

    def test_singleton_same_instance(self, mock_sentence_transformer):
        """Multiple calls should return the same instance."""
        engine1 = get_embedding_engine()
        engine2 = get_embedding_engine()

        assert engine1 is engine2

    def test_engine_has_correct_dimension(self, mock_sentence_transformer):
        """Engine should report 768 dimensions."""
        engine = get_embedding_engine()

        assert engine.dimension == 768
