"""Comprehensive unit tests for SQLAlchemy ORM models.

Covers creation, attributes, relationships, repr formatting, and edge cases
for all models: Source, Transcript, Message, Chunk, Project, Task,
Artifact, TranscriptRelationship, and MiningResult.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import (
    Artifact,
    Base,
    Chunk,
    Message,
    MiningResult,
    Project,
    Source,
    Task,
    Transcript,
    TranscriptRelationship,
)

# ---------------------------------------------------------------------------
# Table registration sanity check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTableRegistry:
    """Ensure all expected tables are registered on the metadata."""

    EXPECTED_TABLES = {
        "sources",
        "transcripts",
        "messages",
        "chunks",
        "projects",
        "tasks",
        "artifacts",
        "transcript_relationships",
        "mining_results",
    }

    async def test_all_tables_exist(self) -> None:
        """Every model should produce a table in ``Base.metadata``."""
        actual_tables = set(Base.metadata.tables.keys())
        missing = TestTableRegistry.EXPECTED_TABLES - actual_tables
        assert not missing, f"Missing tables: {missing}"

    async def test_no_extra_tables(self) -> None:
        """No unexpected tables should exist."""
        actual_tables = set(Base.metadata.tables.keys())
        extra = actual_tables - TestTableRegistry.EXPECTED_TABLES
        assert not extra, f"Unexpected tables: {extra}"


# ---------------------------------------------------------------------------
# Source model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSourceModel:
    """Tests for the ``Source`` model."""

    async def test_create_source(self, db_session: AsyncSession) -> None:
        """A Source can be created with all fields set."""
        source = Source(
            source_type="youtube",
            external_id="dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            description="Rick Astley classic",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            language="en",
            duration_seconds=213,
            metadata_={"channel": "RickAstley"},
        )
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)

        assert source.id is not None
        assert isinstance(source.id, uuid.UUID)
        assert source.source_type == "youtube"
        assert source.title == "Never Gonna Give You Up"
        assert source.metadata_["channel"] == "RickAstley"
        assert source.created_at is not None
        assert source.updated_at is not None

    async def test_source_defaults(self, db_session: AsyncSession) -> None:
        """`Source`` uses sensible defaults for optional fields."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)

        assert source.external_id is None
        assert source.title is None
        assert source.duration_seconds is None

    async def test_source_repr(self, db_session: AsyncSession) -> None:
        """`__repr__`` contains key identifying info."""
        source = Source(source_type="rss", title="Test Feed")
        db_session.add(source)
        await db_session.commit()

        repr_str = repr(source)
        assert "Source" in repr_str
        assert "rss" in repr_str
        assert "Test Feed" in repr_str

    async def test_source_transcript_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """A Source can have associated Transcripts via relationship."""
        source = Source(source_type="youtube", title="Parent")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id, title="Child")
        db_session.add(transcript)
        await db_session.commit()

        stmt = select(Source).where(Source.id == source.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.transcripts) == 1
        assert fetched.transcripts[0].title == "Child"


# ---------------------------------------------------------------------------
# Transcript model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranscriptModel:
    """Tests for the ``Transcript`` model."""

    async def test_create_transcript(self, db_session: AsyncSession) -> None:
        """A Transcript requires a valid source_id."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(
            source_id=source.id,
            title="Meeting Notes",
            raw_text="Alice: Hello everyone...",
            language="en",
            status="completed",
            metadata_={"speakers": ["Alice", "Bob"]},
        )
        db_session.add(transcript)
        await db_session.commit()
        await db_session.refresh(transcript)

        assert transcript.id is not None
        assert transcript.source_id == source.id
        assert transcript.status == "completed"
        assert transcript.metadata_["speakers"] == ["Alice", "Bob"]

    async def test_transcript_default_status(self, db_session: AsyncSession) -> None:
        """Status defaults to ``pending``."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.commit()

        assert transcript.status == "pending"

    async def test_transcript_repr(self, db_session: AsyncSession) -> None:
        """__repr__` is informative."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id, title="My Transcript")
        db_session.add(transcript)
        await db_session.commit()

        repr_str = repr(transcript)
        assert "Transcript" in repr_str
        assert "pending" in repr_str
        assert "My Transcript" in repr_str

    async def test_transcript_messages_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """Messages can be associated with a Transcript."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        msg1 = Message(transcript_id=transcript.id, content="Hello", sequence=0)
        msg2 = Message(transcript_id=transcript.id, content="World", sequence=1)
        db_session.add_all([msg1, msg2])
        await db_session.commit()

        stmt = select(Transcript).where(Transcript.id == transcript.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.messages) == 2
        assert fetched.messages[0].content == "Hello"
        assert fetched.messages[1].content == "World"

    async def test_transcript_chunks_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """Chunks can be associated with a Transcript."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        chunk = Chunk(
            transcript_id=transcript.id,
            text="Hello world",
            chunk_index=0,
            embedding=[0.1] * 768,
        )
        db_session.add(chunk)
        await db_session.commit()

        stmt = select(Transcript).where(Transcript.id == transcript.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.chunks) == 1
        assert fetched.chunks[0].text == "Hello world"

    async def test_transcript_mining_results_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """MiningResults can be associated with a Transcript."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        mining = MiningResult(
            transcript_id=transcript.id,
            miner_type="topics",
            result_data={"topics": ["AI", "ML"]},
            confidence=0.95,
        )
        db_session.add(mining)
        await db_session.commit()

        stmt = select(Transcript).where(Transcript.id == transcript.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.mining_results) == 1
        assert fetched.mining_results[0].miner_type == "topics"


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMessageModel:
    """Tests for the ``Message`` model."""

    async def test_create_message(self, db_session: AsyncSession) -> None:
        """A Message can be created with all fields."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        msg = Message(
            transcript_id=transcript.id,
            speaker="Alice",
            content="Hello, this is a test message.",
            timestamp_seconds=12.5,
            sequence=0,
            metadata_={"confidence": 0.99},
        )
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)

        assert msg.id is not None
        assert msg.speaker == "Alice"
        assert msg.content == "Hello, this is a test message."
        assert msg.timestamp_seconds == 12.5
        assert msg.sequence == 0

    async def test_message_no_speaker(self, db_session: AsyncSession) -> None:
        """Message speaker can be null."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        msg = Message(transcript_id=transcript.id, content="Anonymous message")
        db_session.add(msg)
        await db_session.commit()

        assert msg.speaker is None

    async def test_message_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows speaker and content preview."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        msg = Message(
            transcript_id=transcript.id,
            speaker="Bob",
            content="Short",
        )
        db_session.add(msg)
        await db_session.commit()

        repr_str = repr(msg)
        assert "Message" in repr_str
        assert "Bob" in repr_str
        assert "Short" in repr_str


# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChunkModel:
    """Tests for the ``Chunk`` model."""

    async def test_create_chunk(self, db_session: AsyncSession) -> None:
        """A Chunk can be created with an embedding vector."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        chunk = Chunk(
            transcript_id=transcript.id,
            text="This is a chunk of transcript text.",
            embedding=[0.01] * 768,
            chunk_index=3,
            metadata_={"token_count": 42},
        )
        db_session.add(chunk)
        await db_session.commit()
        await db_session.refresh(chunk)

        assert chunk.id is not None
        assert chunk.transcript_id == transcript.id
        assert chunk.chunk_index == 3
        assert chunk.metadata_["token_count"] == 42

    async def test_chunk_embedding_dimension(self, db_session: AsyncSession) -> None:
        """Embedding vector must have exactly 768 dimensions."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        # Wrong dimension should raise an error
        chunk = Chunk(
            transcript_id=transcript.id,
            text="Bad embedding.",
            embedding=[0.1] * 100,  # only 100 dims
            chunk_index=0,
        )
        db_session.add(chunk)
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_chunk_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows chunk index and text preview."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        chunk = Chunk(
            transcript_id=transcript.id,
            text="Preview text here",
            embedding=[0.0] * 768,
            chunk_index=7,
        )
        db_session.add(chunk)
        await db_session.commit()

        repr_str = repr(chunk)
        assert "Chunk" in repr_str
        assert "7" in repr_str
        assert "Preview" in repr_str

    async def test_chunk_message_id_nullable(
        self, db_session: AsyncSession
    ) -> None:
        """message_id can be null when not linked to a specific message."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        chunk = Chunk(
            transcript_id=transcript.id,
            text="Standalone chunk.",
            embedding=[0.1] * 768,
            chunk_index=0,
            message_id=None,
        )
        db_session.add(chunk)
        await db_session.commit()

        assert chunk.message_id is None


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectModel:
    """Tests for the ``Project`` model."""

    async def test_create_project(self, db_session: AsyncSession) -> None:
        """A Project can be created with all fields."""
        project = Project(
            name="Q3 Planning",
            description="Third quarter planning session",
            status="active",
            metadata_={"owner": "Alice", "color": "#ff0000"},
        )
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)

        assert project.id is not None
        assert project.name == "Q3 Planning"
        assert project.status == "active"
        assert project.metadata_["owner"] == "Alice"

    async def test_project_default_status(self, db_session: AsyncSession) -> None:
        """Status defaults to ``active``."""
        project = Project(name="Minimal")
        db_session.add(project)
        await db_session.commit()

        assert project.status == "active"

    async def test_project_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows name and status."""
        project = Project(name="My Project", status="archived")
        db_session.add(project)
        await db_session.commit()

        repr_str = repr(project)
        assert "Project" in repr_str
        assert "My Project" in repr_str
        assert "archived" in repr_str

    async def test_project_tasks_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """Tasks can be associated with a Project."""
        project = Project(name="With Tasks")
        db_session.add(project)
        await db_session.flush()

        task1 = Task(project_id=project.id, title="Task A")
        task2 = Task(project_id=project.id, title="Task B", status="done")
        db_session.add_all([task1, task2])
        await db_session.commit()

        stmt = select(Project).where(Project.id == project.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.tasks) == 2
        assert {t.title for t in fetched.tasks} == {"Task A", "Task B"}

    async def test_project_artifacts_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """Artifacts can be associated with a Project."""
        project = Project(name="With Artifacts")
        db_session.add(project)
        await db_session.flush()

        artifact = Artifact(
            project_id=project.id,
            artifact_type="summary",
            name="Project Summary",
            content={"summary": "This is a summary."},
        )
        db_session.add(artifact)
        await db_session.commit()

        stmt = select(Project).where(Project.id == project.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()

        assert len(fetched.artifacts) == 1
        assert fetched.artifacts[0].artifact_type == "summary"


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskModel:
    """Tests for the ``Task`` model."""

    async def test_create_task(self, db_session: AsyncSession) -> None:
        """A Task can be created with all fields."""
        project = Project(name="Task Project")
        db_session.add(project)
        await db_session.flush()

        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        task = Task(
            project_id=project.id,
            title="Review pull request",
            description="Please review PR #42",
            status="in_progress",
            priority="high",
            source_transcript_id=transcript.id,
            metadata_={"assignee": "Bob"},
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        assert task.id is not None
        assert task.title == "Review pull request"
        assert task.status == "in_progress"
        assert task.priority == "high"
        assert task.source_transcript_id == transcript.id

    async def test_task_defaults(self, db_session: AsyncSession) -> None:
        """Defaults are applied for optional fields."""
        task = Task(title="Simple Task")
        db_session.add(task)
        await db_session.commit()

        assert task.status == "todo"
        assert task.priority == "medium"
        assert task.project_id is None
        assert task.due_date is None

    async def test_task_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows title, status, and priority."""
        task = Task(title="Urgent Fix", status="done", priority="high")
        db_session.add(task)
        await db_session.commit()

        repr_str = repr(task)
        assert "Task" in repr_str
        assert "Urgent Fix" in repr_str
        assert "done" in repr_str
        assert "high" in repr_str


# ---------------------------------------------------------------------------
# Artifact model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestArtifactModel:
    """Tests for the ``Artifact`` model."""

    async def test_create_artifact(self, db_session: AsyncSession) -> None:
        """An Artifact can be created with structured content."""
        project = Project(name="Artifact Project")
        db_session.add(project)
        await db_session.flush()

        artifact = Artifact(
            project_id=project.id,
            artifact_type="mind_map",
            name="Project Mind Map",
            content={
                "nodes": [
                    {"id": "1", "label": "Root"},
                    {"id": "2", "label": "Branch"},
                ]
            },
            metadata_={"skill": "mind_map_generator"},
        )
        db_session.add(artifact)
        await db_session.commit()
        await db_session.refresh(artifact)

        assert artifact.id is not None
        assert artifact.artifact_type == "mind_map"
        assert len(artifact.content["nodes"]) == 2

    async def test_artifact_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows type and name."""
        artifact = Artifact(
            artifact_type="report",
            name="Weekly Report",
            content={"week": 42},
        )
        db_session.add(artifact)
        await db_session.commit()

        repr_str = repr(artifact)
        assert "Artifact" in repr_str
        assert "report" in repr_str
        assert "Weekly Report" in repr_str


# ---------------------------------------------------------------------------
# TranscriptRelationship model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranscriptRelationshipModel:
    """Tests for the ``TranscriptRelationship`` model."""

    async def test_create_relationship(self, db_session: AsyncSession) -> None:
        """A relationship links two transcripts."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        t1 = Transcript(source_id=source.id, title="Transcript 1")
        t2 = Transcript(source_id=source.id, title="Transcript 2")
        db_session.add_all([t1, t2])
        await db_session.flush()

        rel = TranscriptRelationship(
            transcript_id=t1.id,
            related_transcript_id=t2.id,
            relationship_type="continuation",
            confidence=0.92,
            metadata_={"reason": "same_meeting"},
        )
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)

        assert rel.id is not None
        assert rel.transcript_id == t1.id
        assert rel.related_transcript_id == t2.id
        assert rel.relationship_type == "continuation"
        assert rel.confidence == 0.92

    async def test_relationship_unique_constraint(
        self, db_session: AsyncSession
    ) -> None:
        """Duplicate relationship types between same transcripts are rejected."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        t1 = Transcript(source_id=source.id)
        t2 = Transcript(source_id=source.id)
        db_session.add_all([t1, t2])
        await db_session.flush()

        rel1 = TranscriptRelationship(
            transcript_id=t1.id,
            related_transcript_id=t2.id,
            relationship_type="similar",
        )
        db_session.add(rel1)
        await db_session.commit()

        rel2 = TranscriptRelationship(
            transcript_id=t1.id,
            related_transcript_id=t2.id,
            relationship_type="similar",
        )
        db_session.add(rel2)
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_relationship_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows linked transcript IDs."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        t1 = Transcript(source_id=source.id)
        t2 = Transcript(source_id=source.id)
        db_session.add_all([t1, t2])
        await db_session.flush()

        rel = TranscriptRelationship(
            transcript_id=t1.id,
            related_transcript_id=t2.id,
            relationship_type="related",
        )
        db_session.add(rel)
        await db_session.commit()

        repr_str = repr(rel)
        assert "TranscriptRelationship" in repr_str
        assert "related" in repr_str


# ---------------------------------------------------------------------------
# MiningResult model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMiningResultModel:
    """Tests for the ``MiningResult`` model."""

    async def test_create_mining_result(self, db_session: AsyncSession) -> None:
        """A MiningResult can be created with structured data."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        mining = MiningResult(
            transcript_id=transcript.id,
            miner_type="sentiment",
            result_data={
                "overall": "positive",
                "scores": {"positive": 0.85, "negative": 0.10, "neutral": 0.05},
            },
            confidence=0.88,
        )
        db_session.add(mining)
        await db_session.commit()
        await db_session.refresh(mining)

        assert mining.id is not None
        assert mining.miner_type == "sentiment"
        assert mining.result_data["overall"] == "positive"
        assert mining.confidence == 0.88

    async def test_mining_result_defaults(self, db_session: AsyncSession) -> None:
        """Confidence defaults to 1.0."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        mining = MiningResult(
            transcript_id=transcript.id,
            miner_type="action_items",
            result_data={"items": []},
        )
        db_session.add(mining)
        await db_session.commit()

        assert mining.confidence == 1.0

    async def test_mining_result_repr(self, db_session: AsyncSession) -> None:
        """__repr__` shows transcript_id and miner_type."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        mining = MiningResult(
            transcript_id=transcript.id,
            miner_type="entities",
            result_data={"entities": [{"name": "Alice", "type": "PERSON"}]},
        )
        db_session.add(mining)
        await db_session.commit()

        repr_str = repr(mining)
        assert "MiningResult" in repr_str
        assert "entities" in repr_str


# ---------------------------------------------------------------------------
# Cascade delete tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCascadeDeletes:
    """Ensure cascade deletes work correctly across relationships."""

    async def test_delete_source_cascades_to_transcripts(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a Source removes its Transcripts."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        await db_session.delete(source)
        await db_session.commit()

        stmt = select(Transcript).where(Transcript.id == transcript.id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None

    async def test_delete_transcript_cascades_to_messages(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a Transcript removes its Messages."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        msg = Message(transcript_id=transcript.id, content="Goodbye")
        db_session.add(msg)
        await db_session.flush()

        await db_session.delete(transcript)
        await db_session.commit()

        stmt = select(Message).where(Message.id == msg.id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None

    async def test_delete_transcript_cascades_to_chunks(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a Transcript removes its Chunks."""
        source = Source(source_type="audio_file")
        db_session.add(source)
        await db_session.flush()

        transcript = Transcript(source_id=source.id)
        db_session.add(transcript)
        await db_session.flush()

        chunk = Chunk(
            transcript_id=transcript.id,
            text="chunk text",
            embedding=[0.5] * 768,
        )
        db_session.add(chunk)
        await db_session.flush()

        await db_session.delete(transcript)
        await db_session.commit()

        stmt = select(Chunk).where(Chunk.id == chunk.id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None

    async def test_delete_project_cascades_to_tasks(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a Project removes its Tasks."""
        project = Project(name="Delete Me")
        db_session.add(project)
        await db_session.flush()

        task = Task(project_id=project.id, title="Orphan Task")
        db_session.add(task)
        await db_session.flush()

        await db_session.delete(project)
        await db_session.commit()

        stmt = select(Task).where(Task.id == task.id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None

    async def test_delete_project_cascades_to_artifacts(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting a Project removes its Artifacts."""
        project = Project(name="Delete Me Too")
        db_session.add(project)
        await db_session.flush()

        artifact = Artifact(
            project_id=project.id,
            artifact_type="summary",
            name="Gone",
            content={},
        )
        db_session.add(artifact)
        await db_session.flush()

        await db_session.delete(project)
        await db_session.commit()

        stmt = select(Artifact).where(Artifact.id == artifact.id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None
