"""Abstract base classes and data models for the transcript skill system.

Defines the core abstractions that every transcript extraction skill must
implement, along with the rich data-transfer objects used to represent
parsed conversation transcripts in a normalised, provider-agnostic form.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill metadata
# ---------------------------------------------------------------------------


@dataclass
class SkillMetadata:
    """Human- and machine-readable metadata describing a single skill.

    Attributes:
        name: Machine-friendly identifier (snake_case).
        version: Semantic version string, e.g. ``"1.0.0"``.
        display_name: Human-friendly title shown in UI listings.
        description: One or two sentences explaining what the skill does.
        supported_formats: File extensions this skill can consume, e.g.
            ``[".jsonl", ".json"]``.
        priority: Conflict-resolution priority. **Lower** values win when two
            skills return the same ``can_handle`` score.  Default ``100``.
        enabled: Whether the skill is active and available for discovery.
        author: Name or handle of the skill author.
        url: Link to documentation or source code.
    """

    name: str
    version: str
    display_name: str
    description: str
    supported_formats: list[str]
    priority: int = 100  # Lower = higher priority for conflict resolution
    enabled: bool = True
    author: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# Normalised content model
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """A typed content block inside a :class:`NormalizedMessage`.

    Represents rich content such as code snippets, tool calls, tool
    results, or inline images that a provider may embed in a message.

    Attributes:
        type: Block category — ``"text"``, ``"code"``, ``"tool_use"``,
            ``"tool_result"``, or ``"image"``.
        text: The primary textual payload.
        language: Programming language for ``type="code"`` blocks.
        tool_name: Function name for ``type="tool_use"`` blocks.
        tool_input: Arguments dict for ``type="tool_use"`` blocks.
        tool_use_id: Correlation ID linking a tool call to its result.
        tool_result: Serialized result string for ``type="tool_result"``.
        mime_type: MIME type for binary/image content.
    """

    type: str  # text, code, tool_use, tool_result, image
    text: str = ""
    language: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_use_id: Optional[str] = None
    tool_result: Optional[str] = None
    mime_type: Optional[str] = None


@dataclass
class NormalizedMessage:
    """A single message within a conversation, in a provider-agnostic form.

    This dataclass is **backward-compatible** with the pipeline normaliser
    which expects ``speaker`` (not ``role``) and ``sequence`` fields.
    The ``role`` alias property maps to ``speaker`` for newer code.

    Attributes:
        speaker: Who produced the message — ``"user"``, ``"assistant"``,
            ``"system"``, or ``"tool"``.  Maps to the ``speaker`` column in
            the DB.
        content: Raw string or a list of :class:`ContentBlock` objects when
            the provider delivers rich / structured content.
        sequence: Zero-based order of this message within the transcript.
        timestamp: A :class:`~datetime.datetime` or ISO-8601 string if
            available.  The normaliser calls ``.timestamp()`` on it when it
            is a ``datetime``.
        message_type: Semantic category — ``"message"``, ``"tool_use"``,
            ``"tool_result"``, ``"thinking"``, ``"summary"``.
        model: Model name or identifier (e.g. ``"claude-sonnet-4-20250514"``).
        metadata: Provider-specific key-value store.
    """

    speaker: Optional[str] = None
    content: str | list[Any] | dict[str, Any] = ""
    sequence: int = 0
    timestamp: datetime | str | None = None
    message_type: str = "message"
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def role(self) -> str:
        """Alias for ``speaker`` (returns ``"unknown"`` when *speaker* is ``None``)."""
        return self.speaker or "unknown"

    @role.setter
    def role(self, value: str) -> None:
        """Set ``speaker`` via the ``role`` alias."""
        self.speaker = value


# ---------------------------------------------------------------------------
# Extraction result
# ---------------------------------------------------------------------------


@dataclass
class ExtractedTranscript:
    """The artifact produced by a skill after parsing a source file.

    This dataclass is **backward-compatible** with the pipeline normaliser
    which expects ``source_type``, ``title``, ``raw_text``, ``language``,
    ``messages``, and ``metadata`` fields.

    Attributes:
        source_type: Provider identifier (e.g. ``"claude_code"``).  Alias for
            :attr:`skill_name` when not provided explicitly.
        title: Human-readable transcript title.
        raw_text: The full raw text of the transcript (concatenated messages).
        language: ISO-639-1 language code.
        messages: Ordered list of normalised conversation messages.
        metadata: Arbitrary additional data from the provider format.
        source_path: Absolute path to the file that was parsed.
        skill_name: Identifier of the skill that produced this result.
        session_id: Optional session identifier extracted from the file.
        project_name: Optional project name inferred from path or metadata.
        model: AI model identifier if known.
        started_at: ISO-8601 timestamp for session start.
        ended_at: ISO-8601 timestamp for session end.
        warnings: Non-fatal issues encountered during parsing.
        errors: Fatal errors that prevented full extraction.
        raw_lines: Total lines / records read from source.
        parsed_lines: Lines / records successfully converted to messages.
    """

    source_type: str = ""
    title: Optional[str] = None
    raw_text: Optional[str] = None
    language: Optional[str] = None
    messages: list[NormalizedMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # New extended fields
    source_path: Optional[Path] = None
    skill_name: str = ""
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    model: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_lines: int = 0
    parsed_lines: int = 0

    def __post_init__(self) -> None:
        """Ensure backward-compatibility aliases are populated."""
        if not self.source_type and self.skill_name:
            self.source_type = self.skill_name
        if not self.skill_name and self.source_type:
            self.skill_name = self.source_type

    @property
    def success(self) -> bool:
        """Return ``True`` if at least one message was extracted."""
        return len(self.messages) > 0

    @property
    def message_count(self) -> int:
        """Return the number of extracted messages."""
        return len(self.messages)


# ---------------------------------------------------------------------------
# Abstract base class for skills
# ---------------------------------------------------------------------------


class TranscriptSkill(ABC):
    """Abstract base class for all transcript extraction skills.

    Each concrete skill implements four class-level hooks:

    1. :meth:`metadata` — returns :class:`SkillMetadata`.
    2. :meth:`can_handle` — returns a confidence score (``0.0`` to ``1.0``)
       indicating how strongly this skill believes it can parse *path*.
    3. :meth:`extract_transcripts` — lazily yields
       :class:`ExtractedTranscript` objects.
    4. :meth:`validate_source` — pre-flight check returning a list of
       human-readable issues (empty list == valid).

    **IMPORTANT**: ``metadata`` is a ``@classmethod`` (NOT a
    ``@classmethod @property`` combo).  Python 3.12+ removed the
    classmethod+property descriptor stack, so callers must use
    ``cls.metadata()`` (with parentheses).
    """

    @classmethod
    @abstractmethod
    def metadata(cls) -> SkillMetadata:
        """Return the static metadata descriptor for this skill."""
        ...

    @classmethod
    @abstractmethod
    def can_handle(cls, path: Path) -> float:
        """Return a confidence score in ``[0.0, 1.0]``.

        Scoring convention:

        * ``1.0`` — exact match (the path follows the provider's canonical
          directory or naming convention).
        * ``0.5`` — partial / filename match.
        * ``0.3`` — related directory (same parent tool, different sub-dir).
        * ``0.1`` — generic format match (e.g. any ``.jsonl`` file).
        * ``0.0`` — no match at all.
        """
        ...

    @abstractmethod
    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Extract one or more transcripts from *path*.

        Args:
            path: File system location to parse.
            **options: Provider-specific knobs (e.g. encoding, date filter).

        Yields:
            :class:`ExtractedTranscript` instances (one per conversation
            session found in the source).
        """
        ...

    @abstractmethod
    def validate_source(self, path: Path) -> list[str]:
        """Validate that *path* looks parseable **before** extraction.

        Returns:
            A list of human-readable issue descriptions.  An empty list
            means the source appears valid.
        """
        ...
