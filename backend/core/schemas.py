"""Pydantic v2 request / response schemas for the Burdello Bum-Bum API.

All schemas use ``ConfigDict(from_attributes=True)`` so they can be
populated directly from SQLAlchemy ORM instances.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator


# ===========================================================================
# Source Schemas
# ===========================================================================


class SourceCreate(BaseModel):
    """Request body for creating a new source."""

    source_type: str = Field(..., max_length=50)
    external_id: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, max_length=10)
    duration_seconds: int | None = None
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class SourceResponse(BaseModel):
    """Response model for a source."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    external_id: str | None
    title: str | None
    description: str | None
    url: str | None
    language: str | None
    duration_seconds: int | None
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    """Paginated list of sources (matches the /sources list endpoint payload)."""

    total: int
    items: list[SourceResponse]


# ===========================================================================
# Message Schemas
# ===========================================================================


class MessageCreate(BaseModel):
    """Request body for creating a message within a transcript."""

    speaker: str | None = Field(default=None, max_length=255)
    content: str
    timestamp_seconds: float | None = None
    sequence: int = 0
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class MessageResponse(BaseModel):
    """Response model for a transcript message."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transcript_id: uuid.UUID
    speaker: str | None
    content: str
    timestamp_seconds: float | None
    sequence: int
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


# ===========================================================================
# Transcript Schemas
# ===========================================================================


class TranscriptCreate(BaseModel):
    """Request body for creating a new transcript."""

    source_id: uuid.UUID
    session_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    raw_text: str | None = None
    language: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class TranscriptResponse(BaseModel):
    """Response model for a transcript."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    session_id: str | None = None
    title: str | None
    language: str | None
    status: str
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_name(self) -> str | None:
        """Session/project name derived from the transcript (path-based)."""
        return (self.metadata or {}).get("project_name")


class TranscriptSummary(BaseModel):
    """Lightweight summary of a transcript for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: str | None = None
    title: str | None
    status: str
    message_count: int | None = None
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_name(self) -> str | None:
        """Session/project name derived from the transcript (path-based)."""
        return (self.metadata or {}).get("project_name")


class TranscriptListResponse(BaseModel):
    """Paginated list of transcript summaries."""

    total: int
    page: int
    page_size: int
    items: list[TranscriptSummary]


class TranscriptDetailResponse(TranscriptResponse):
    """Full transcript response including messages and source info."""

    source: SourceResponse | None = None
    messages: list[MessageResponse] | None = None


# ===========================================================================
# Project Schemas
# ===========================================================================


class ProjectCreate(BaseModel):
    """Request body for creating a new project."""

    name: str = Field(..., max_length=255)
    description: str | None = None
    notes: str | None = None
    tags: list[str] | None = Field(default_factory=list)
    pinned: bool | None = False
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class ProjectResponse(BaseModel):
    """Response model for a project."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: str
    notes: str | None
    tags: list[str] | None
    pinned: bool
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    # Populated by the list/detail endpoints (aggregated from tasks).
    task_count: int = 0
    completed_task_count: int = 0
    transcript_count: int = 0
    last_activity_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence(self) -> float | None:
        """Mining confidence, lifted from metadata for the UI."""
        val = (self.metadata or {}).get("confidence")
        return float(val) if isinstance(val, (int, float)) else None


class ProjectStats(BaseModel):
    """Statistics for a single project."""

    total_tasks: int
    tasks_done: int
    tasks_todo: int
    total_artifacts: int


class ProjectDetailResponse(ProjectResponse):
    """Full project response including tasks and artifacts."""

    tasks: list[TaskSummary] | None = None
    artifacts: list[ArtifactSummary] | None = None
    stats: ProjectStats | None = None


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    total: int
    page: int
    page_size: int
    items: list[ProjectResponse]


# ===========================================================================
# Task Schemas
# ===========================================================================


class TaskCreate(BaseModel):
    """Request body for creating a task."""

    project_id: uuid.UUID | None = None
    title: str = Field(..., max_length=500)
    description: str | None = None
    status: str = "todo"
    priority: str | None = "medium"
    due_date: datetime | None = None
    source_transcript_id: uuid.UUID | None = None
    notes: str | None = None
    tags: list[str] | None = Field(default_factory=list)
    pinned: bool | None = False
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """Response model for a task."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: str | None
    due_date: datetime | None
    source_transcript_id: uuid.UUID | None
    notes: str | None
    tags: list[str] | None
    pinned: bool
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence(self) -> float | None:
        """Mining confidence, lifted from metadata for the UI."""
        val = (self.metadata or {}).get("confidence")
        return float(val) if isinstance(val, (int, float)) else None


class TaskSummary(BaseModel):
    """Lightweight summary of a task for list / nested views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    priority: str | None


class TaskListResponse(BaseModel):
    """Paginated list of tasks."""

    total: int
    page: int
    page_size: int
    items: list[TaskResponse]


class TaskBatchStatusUpdate(BaseModel):
    """Request body for batch task status updates."""

    task_ids: list[uuid.UUID]
    status: str


class TaskBatchResult(BaseModel):
    """Result of a batch task operation."""

    updated: int
    task_ids: list[uuid.UUID]


# ===========================================================================
# Artifact Schemas
# ===========================================================================

# High-level deliverables only. Routine source files, tests, configs and
# one-off snippets should be excluded from artifact extraction.
ARTIFACT_TYPES = (
    "research",
    "plan",
    "html",
    "deck",
    "document",
    "link",
    "report",
    "diagram",
    "spec",
    "finding",
)


class ArtifactCreate(BaseModel):
    """Request body for creating an artifact."""

    project_id: uuid.UUID | None = None
    artifact_type: str = Field(..., max_length=50)
    name: str = Field(..., max_length=255)
    content: dict[str, Any] | None = Field(default_factory=dict)
    source_transcript_id: uuid.UUID | None = None
    notes: str | None = None
    tags: list[str] | None = Field(default_factory=list)
    pinned: bool | None = False
    metadata: dict[str, Any] | None = Field(default_factory=dict)

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str) -> str:
        """Only accept high-level artifact types."""
        normalized = value.lower().strip()
        if normalized not in ARTIFACT_TYPES:
            raise ValueError(
                f"artifact_type must be one of {ARTIFACT_TYPES}, got {value!r}"
            )
        return normalized


class ArtifactResponse(BaseModel):
    """Response model for an artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    artifact_type: str
    name: str
    content: dict[str, Any]
    source_transcript_id: uuid.UUID | None
    notes: str | None
    tags: list[str] | None
    pinned: bool
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


class ArtifactSummary(BaseModel):
    """Lightweight summary of an artifact for list / nested views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    artifact_type: str
    name: str


class ArtifactListResponse(BaseModel):
    """Paginated list of artifacts."""

    total: int
    page: int
    page_size: int
    items: list[ArtifactResponse]


# ===========================================================================
# Bookmark Schemas
# ===========================================================================


class BookmarkCreate(BaseModel):
    """Request body for creating a bookmark."""

    note_text: str = Field(..., min_length=1, max_length=4000)
    project_id: uuid.UUID | None = None
    project_name: str | None = Field(default=None, max_length=255)
    session_id: str | None = Field(default=None, max_length=255)
    session_path: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default_factory=list)
    pinned: bool | None = False
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class BookmarkUpdate(BaseModel):
    """Request body for patching a bookmark (all fields optional).

    Distinct from ``BookmarkCreate`` so a partial update (e.g. toggling
    ``pinned``) does not require resending ``note_text``. ``note_text`` is
    constrained to a non-empty string when present so a PATCH can never blank
    out the NOT NULL note column.
    """

    note_text: str | None = Field(default=None, min_length=1, max_length=4000)
    pinned: bool | None = None
    tags: list[str] | None = None


class BookmarkResponse(BaseModel):
    """Response model for a bookmark."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    transcript_id: uuid.UUID | None
    session_id: str | None
    session_path: str | None
    note_text: str
    author: str | None
    ingest_status: str
    ingest_job_id: str | None
    tags: list[str] | None
    pinned: bool
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


class BookmarkListResponse(BaseModel):
    """List of bookmarks ({total, items} envelope)."""

    total: int
    items: list[BookmarkResponse]


# ===========================================================================
# Search Schemas
# ===========================================================================


class SearchFilters(BaseModel):
    """Optional filters to narrow search results."""

    transcript_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    source_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class SearchRequest(BaseModel):
    """Request body for a hybrid search query."""

    query: str = Field(..., min_length=1)
    filters: SearchFilters | None = Field(default_factory=SearchFilters)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    """A single search result from the hybrid engine."""

    chunk_id: uuid.UUID
    transcript_id: uuid.UUID
    text: str
    score: float
    metadata: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    """Response model for a hybrid search query."""

    total: int
    query: str
    results: list[SearchResult]


class QACitation(BaseModel):
    """A source chunk cited in a Q&A answer."""

    chunk_id: uuid.UUID
    transcript_id: uuid.UUID
    text: str
    score: float


class QARequest(BaseModel):
    """Request body for a natural-language Q&A query."""

    question: str = Field(..., min_length=1, max_length=2000)
    filters: SearchFilters | None = None
    top_k: int = Field(default=6, ge=1, le=20)


class QAResponse(BaseModel):
    """Response to a natural-language Q&A query."""

    question: str
    answer: str
    citations: list[QACitation]


# ===========================================================================
# Mining Result Schemas
# ===========================================================================


class MiningResultResponse(BaseModel):
    """Response model for a mining result."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transcript_id: uuid.UUID
    miner_type: str
    result_data: dict[str, Any]
    confidence: float | None
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


# ===========================================================================
# Transcript Relationship Schemas
# ===========================================================================


class TranscriptRelationshipResponse(BaseModel):
    """Response model for a transcript relationship."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transcript_id: uuid.UUID
    related_transcript_id: uuid.UUID
    relationship_type: str
    confidence: float | None
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("metadata_", "metadata")
    )
    created_at: datetime
    updated_at: datetime


# ===========================================================================
# Skill Schemas
# ===========================================================================


class SkillInfoResponse(BaseModel):
    """Metadata about an available AI skill."""

    name: str
    description: str
    parameters: dict[str, Any] | None = None


# ===========================================================================
# Todoist Sync Schemas
# ===========================================================================


class TodoistExportRequest(BaseModel):
    """Request body for exporting tasks to Todoist."""

    project_id: uuid.UUID
    task_ids: list[uuid.UUID] | None = None
    todoist_project_id: str | None = None
    include_done: bool = False


class TodoistExportResponse(BaseModel):
    """Response model for a Todoist export operation."""

    exported_count: int
    todoist_project_id: str | None = None


class TodoistProjectSummary(BaseModel):
    """Compact representation of a Todoist project."""

    id: str
    name: str


class TodoistEpicMatch(BaseModel):
    """Result of matching an epic to an existing Todoist project."""

    todoist_project_id: str | None = None
    todoist_project_name: str | None = None
    score: float | None = None
    reason: str | None = None
    source: str | None = None


class TodoistSyncEpic(BaseModel):
    """Grouped epic bucket produced by the sync planner."""

    epic_key: str
    epic_name: str
    summary: str | None = None
    task_count: int
    task_ids: list[uuid.UUID]
    match: TodoistEpicMatch


class TodoistSyncPlanResponse(BaseModel):
    """Preview output for a Todoist sync run."""

    project_id: uuid.UUID
    project_name: str
    include_done: bool
    todoist_inbox_project_id: str | None = None
    todoist_projects_error: str | None = None
    todoist_projects: list[TodoistProjectSummary]
    epics: list[TodoistSyncEpic]
    skipped_done: int = 0
    total_tasks: int = 0
    eligible_tasks: int = 0


class TodoistSyncRunSummary(BaseModel):
    """Stored metadata for a completed Todoist sync run."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    status: str
    include_done: bool
    todoist_inbox_project_id: str | None = None
    created_at: datetime
    updated_at: datetime
    error_text: str | None = None
    metrics: dict[str, Any] | None = None


class TodoistSyncRunDetail(TodoistSyncRunSummary):
    """Full Todoist sync run, including the persisted plan/result payloads."""

    plan_data: dict[str, Any] | None = None
    result_data: dict[str, Any] | None = None


class TodoistSyncRunListResponse(BaseModel):
    """Paginated sync history."""

    items: list[TodoistSyncRunSummary]
    total: int


# ===========================================================================
# Stats Schemas
# ===========================================================================


class StatsResponse(BaseModel):
    """Global platform statistics (matches the frontend Stats contract)."""

    total_sources: int
    total_transcripts: int
    total_projects: int
    total_tasks: int
    total_artifacts: int
    total_messages: int
    provider_breakdown: dict[str, int]
    status_breakdown: dict[str, int]


# ===========================================================================
# Health
# ===========================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
