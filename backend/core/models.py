"""SQLAlchemy ORM models for the Burdello Bum-Bum platform.

Defines all database tables including sources, transcripts, messages, chunks,
projects, tasks, artifacts, transcript relationships, and mining results.
Uses UUID primary keys, JSONB for metadata, and pgvector VECTOR for embeddings.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.

    Uses JSONB as the native type for ``dict``-mapped columns.
    """

    type_annotation_map: dict[type, Any] = {
        dict: JSONB,
    }


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Source(Base, TimestampMixin):
    """An external source (e.g. YouTube, audio file, podcast)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of source: youtube, audio_file, rss, etc.",
    )
    external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="External identifier (YouTube video ID, etc.)",
    )
    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="ISO 639-1 language code",
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
        comment="Flexible metadata storage",
    )

    # Relationships
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Source(id={self.id!s}, "
            f"source_type={self.source_type!r}, "
            f"title={self.title!r})>"
        )


class Transcript(Base, TimestampMixin):
    """A transcript extracted from a source."""

    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Agent session UUID (e.g. CLAUDE_CODE_SESSION_ID); link key for bookmarks",
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Full raw transcript text",
    )
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending, processing, completed, error",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="transcripts")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    relationships: Mapped[list["TranscriptRelationship"]] = relationship(
        back_populates="transcript",
        foreign_keys="TranscriptRelationship.transcript_id",
        cascade="all, delete-orphan",
    )
    mining_results: Mapped[list["MiningResult"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Transcript(id={self.id!s}, "
            f"source_id={self.source_id!s}, "
            f"status={self.status!r}, "
            f"title={self.title!r})>"
        )


class Message(Base, TimestampMixin):
    """An individual message / utterance within a transcript."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    speaker: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    timestamp_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Offset in seconds from start of recording",
    )
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Message order within the transcript",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    transcript: Mapped["Transcript"] = relationship(
        back_populates="messages",
    )

    def __repr__(self) -> str:
        speaker = self.speaker or "unknown"
        content_preview = self.content[:50] if self.content else ""
        return (
            f"<Message(id={self.id!s}, "
            f"speaker={speaker!r}, "
            f"seq={self.sequence}, "
            f"content={content_preview!r}...)>"
        )


class Chunk(Base, TimestampMixin):
    """A vector-searchable chunk of transcript text."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    embedding: Mapped[Any] = mapped_column(
        Vector(768),
        nullable=True,
        comment="768-dim cosine-normalised embedding from nomic-embed-text-v2",
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    transcript: Mapped["Transcript"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        text_preview = self.text[:50] if self.text else ""
        return (
            f"<Chunk(id={self.id!s}, "
            f"transcript_id={self.transcript_id!s}, "
            f"index={self.chunk_index}, "
            f"text={text_preview!r}...)>"
        )


class Project(Base, TimestampMixin):
    """A project that groups transcripts, tasks, and artifacts."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="active, archived, deleted",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        server_default="{}",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    # No cascade: the DB FK is ON DELETE SET NULL, so deleting a project
    # orphans its bookmarks rather than deleting them. Adding
    # cascade="all, delete-orphan" here would contradict that.
    bookmarks: Mapped[list["Bookmark"]] = relationship(
        back_populates="project",
    )
    todoist_sync_runs: Mapped[list["TodoistSyncRun"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Project(id={self.id!s}, "
            f"name={self.name!r}, "
            f"status={self.status!r})>"
        )


class Task(Base, TimestampMixin):
    """A task extracted from transcripts via AI mining."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="todo",
        comment="todo, in_progress, done, cancelled",
    )
    priority: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default="medium",
        comment="low, medium, high",
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_transcript_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transcripts.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        server_default="{}",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="tasks")
    todoist_link: Mapped["TodoistTaskLink | None"] = relationship(
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Task(id={self.id!s}, "
            f"title={self.title!r}, "
            f"status={self.status!r}, "
            f"priority={self.priority!r})>"
        )


class Artifact(Base, TimestampMixin):
    """An artifact generated by AI skills (e.g. summary, mind-map)."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type: summary, mind_map, timeline, report, etc.",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    content: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Structured artifact content",
    )
    source_transcript_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transcripts.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        server_default="{}",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="artifacts")

    def __repr__(self) -> str:
        return (
            f"<Artifact(id={self.id!s}, "
            f"type={self.artifact_type!r}, "
            f"name={self.name!r})>"
        )


class TranscriptRelationship(Base, TimestampMixin):
    """A relationship link between two transcripts."""

    __tablename__ = "transcript_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    related_transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="related",
        comment="related, continuation, similar, etc.",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=0.0,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    transcript: Mapped["Transcript"] = relationship(
        back_populates="relationships",
        foreign_keys=[transcript_id],
    )
    related_transcript: Mapped["Transcript"] = relationship(
        foreign_keys=[related_transcript_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "transcript_id",
            "related_transcript_id",
            "relationship_type",
            name="uq_transcript_relationship",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TranscriptRelationship(id={self.id!s}, "
            f"transcript_id={self.transcript_id!s}, "
            f"related_id={self.related_transcript_id!s}, "
            f"type={self.relationship_type!r})>"
        )


class MiningResult(Base, TimestampMixin):
    """Results from AI mining a transcript (topics, sentiment, entities)."""

    __tablename__ = "mining_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    miner_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="topics, sentiment, entities, action_items, etc.",
    )
    result_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Structured mining result data",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=1.0,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    transcript: Mapped["Transcript"] = relationship(
        back_populates="mining_results",
    )

    def __repr__(self) -> str:
        return (
            f"<MiningResult(id={self.id!s}, "
            f"transcript_id={self.transcript_id!s}, "
            f"miner_type={self.miner_type!r})>"
        )


class Bookmark(Base, TimestampMixin):
    """An agent-authored mark on a session — something to revisit later."""

    __tablename__ = "bookmarks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transcripts.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Agent session UUID; correlation key to Transcript.session_id",
    )
    session_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Display + focused-ingest hint only; not used as a join key",
    )
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ingest_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="none",
        comment="none, pending, linked, failed",
    )
    ingest_job_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Celery result id for the focused-ingest job (observability)",
    )
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="bookmarks")
    transcript: Mapped["Transcript"] = relationship()

    __table_args__ = (
        # Composite index for the default list ordering (project, pinned, recency).
        Index("ix_bookmarks_list", "project_id", "pinned", "created_at"),
        # Partial index used by the session_id-keyed linker to find unlinked rows.
        Index(
            "ix_bookmarks_unlinked",
            "session_id",
            postgresql_where=text("transcript_id IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        note_preview = self.note_text[:50] if self.note_text else ""
        return (
            f"<Bookmark(id={self.id!s}, "
            f"project_id={self.project_id!s}, "
            f"session_id={self.session_id!r}, "
            f"note={note_preview!r}...)>"
        )


class TodoistSyncRun(Base, TimestampMixin):
    """A single Todoist sync execution for a Burdello project."""

    __tablename__ = "todoist_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        comment="running, completed, partial, failed",
    )
    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="auto",
        comment="auto, manual, dry_run",
    )
    include_done: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    todoist_inbox_project_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    plan_data: Mapped[dict | None] = mapped_column(
        "plan_data",
        JSONB,
        nullable=True,
        default=dict,
    )
    result_data: Mapped[dict | None] = mapped_column(
        "result_data",
        JSONB,
        nullable=True,
        default=dict,
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    project: Mapped["Project"] = relationship(back_populates="todoist_sync_runs")
    task_links: Mapped[list["TodoistTaskLink"]] = relationship(
        back_populates="sync_run",
    )

    def __repr__(self) -> str:
        return (
            f"<TodoistSyncRun(id={self.id!s}, "
            f"project_id={self.project_id!s}, "
            f"status={self.status!r})>"
        )


class TodoistTaskLink(Base, TimestampMixin):
    """Stable mapping between a Burdello task and a Todoist task."""

    __tablename__ = "todoist_task_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    epic_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    epic_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    todoist_project_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    todoist_project_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    todoist_task_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("todoist_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_payload: Mapped[dict | None] = mapped_column(
        "last_payload",
        JSONB,
        nullable=True,
        default=dict,
    )
    last_result: Mapped[dict | None] = mapped_column(
        "last_result",
        JSONB,
        nullable=True,
        default=dict,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    task: Mapped["Task"] = relationship(back_populates="todoist_link")
    sync_run: Mapped["TodoistSyncRun | None"] = relationship(
        back_populates="task_links",
    )

    def __repr__(self) -> str:
        return (
            f"<TodoistTaskLink(id={self.id!s}, "
            f"task_id={self.task_id!s}, "
            f"todoist_task_id={self.todoist_task_id!r})>"
        )
