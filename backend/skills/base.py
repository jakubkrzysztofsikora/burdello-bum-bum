"""Base dataclasses and abstract class for skill-extracted transcript data.

Provides ``ContentBlock``, ``SkillMetadata``, ``NormalizedMessage``,
``ExtractedTranscript``, and ``TranscriptSkill`` — the standard
interchange format between provider-specific extraction skills and
the normalisation pipeline.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# ContentBlock
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """A structured content block within a message (text, image, tool-use, etc.).

    Attributes:
        type: The block type — ``text``, ``tool_use``, ``tool_result``,
            ``image``, ``thinking``, etc.
        text: Plain-text content (primary for ``text`` and ``thinking``).
        source: For ``image`` blocks — a dict with ``type`` and ``media_type``.
        tool_use_id: For ``tool_result`` blocks — references the matching
            ``tool_use`` block.
        name: For ``tool_use`` blocks — the tool name.
        input: For ``tool_use`` blocks — the tool arguments.
        output: For ``tool_result`` blocks — the tool output.
        error: For ``tool_result`` blocks — error message if the tool failed.
        metadata: Additional provider-specific fields.
    """

    type: str = "text"
    text: str | None = None
    source: dict[str, Any] | None = None
    tool_use_id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SkillMetadata
# ---------------------------------------------------------------------------


@dataclass
class SkillMetadata:
    """Metadata describing a transcript extraction skill.

    Attributes:
        name: Machine-readable skill name (e.g. ``claude_code``).
        version: Semantic version string.
        display_name: Human-readable name.
        description: Short description of what the skill does.
        supported_formats: List of file extensions this skill handles.
        priority: Lower numbers = higher priority (0 is highest).
        enabled: Whether the skill is active.
        author: Author or team name.
        url: Optional URL to documentation.
    """

    name: str
    version: str = "1.0.0"
    display_name: str = ""
    description: str = ""
    supported_formats: list[str] = field(default_factory=list)
    priority: int = 100
    enabled: bool = True
    author: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        """Set display_name from name if not provided."""
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# NormalizedMessage
# ---------------------------------------------------------------------------


@dataclass
class NormalizedMessage:
    """A single message / utterance extracted from a transcript source.

    Attributes:
        role: The speaker role — ``user``, ``assistant``, ``system``, ``tool``.
        content: The text content of the message. May be a plain string or
            a list of ``ContentBlock`` objects.
        timestamp: Optional wall-clock timestamp (ISO-8601 string).
        model: The AI model name that produced this message, if applicable.
        metadata: Extra provider-specific fields.
        sequence: Zero-based order index within the transcript.
    """

    role: str | None = None
    content: str | list[ContentBlock] = ""
    timestamp: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0

    # Legacy alias for compatibility
    @property
    def speaker(self) -> str | None:
        """Return the role as speaker (legacy alias)."""
        return self.role

    @speaker.setter
    def speaker(self, value: str | None) -> None:
        """Set the role via speaker (legacy alias)."""
        self.role = value


# ---------------------------------------------------------------------------
# ExtractedTranscript
# ---------------------------------------------------------------------------


@dataclass
class ExtractedTranscript:
    """The result of extracting a transcript from a provider-specific source.

    Attributes:
        source_path: Path to the source file that was parsed.
        skill_name: Name of the skill that performed extraction.
        project_name: Inferred project name from directory structure.
        messages: List of normalised messages in conversation order.
        model: AI model identifier used in the session.
        started_at: Session start timestamp (ISO-8601).
        ended_at: Session end timestamp (ISO-8601).
        raw_lines: Total lines read from the source.
        parsed_lines: Number of lines successfully parsed into messages.
        errors: Non-fatal errors encountered during extraction.
        warnings: Warnings encountered during extraction.
        metadata: Extra provider-specific metadata.
        # Legacy fields for pipeline compatibility
        source_type: str = "unknown"
        title: str | None = None
        raw_text: str = ""
        language: str = "en"
    """

    # Primary fields (used by the existing skill system)
    source_path: Path | None = None
    skill_name: str = ""
    project_name: str | None = None
    messages: list[NormalizedMessage] = field(default_factory=list)
    model: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    raw_lines: int = 0
    parsed_lines: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Legacy fields for pipeline compatibility
    source_type: str = "unknown"
    title: str | None = None
    raw_text: str = ""
    language: str = "en"


# ---------------------------------------------------------------------------
# TranscriptSkill (abstract base)
# ---------------------------------------------------------------------------


class TranscriptSkill(ABC):
    """Abstract base class for transcript extraction skills.

    Concrete subclasses must implement:

    * :meth:`metadata` — classmethod returning ``SkillMetadata``.
    * :meth:`can_handle` — classmethod scoring how well this skill
      can parse a given file path.
    * :meth:`extract_transcripts` — instance method yielding
      ``ExtractedTranscript`` objects.
    """

    @classmethod
    @abstractmethod
    def metadata(cls) -> SkillMetadata:
        """Return metadata describing this skill.

        Returns:
            A ``SkillMetadata`` instance with name, version, formats, etc.
        """

    @classmethod
    @abstractmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        Args:
            path: File system path to evaluate.

        Returns:
            A confidence score in the range ``[0.0, 1.0]`` where ``1.0``
            means "definitely can handle this file" and ``0.0`` means
            "cannot handle this file at all".
        """

    @abstractmethod
    def extract_transcripts(
        self,
        path: Path,
        **options: object,
    ) -> Iterator[ExtractedTranscript]:
        """Extract transcripts from the given file path.

        Args:
            path: File system path to parse.
            **options: Extra extraction options (e.g. encoding, chunk size).

        Yields:
            ``ExtractedTranscript`` objects containing the parsed messages.
        """

    def validate_source(self, path: Path) -> list[str]:
        """Return a list of issues with the source file.

        Default implementation just checks the file exists and is readable.

        Args:
            path: File system path to validate.

        Returns:
            List of issue descriptions (empty if no issues).
        """
        issues: list[str] = []
        resolved = path.resolve()

        if not resolved.exists():
            issues.append(f"Path does not exist: {resolved}")
        elif not resolved.is_file():
            issues.append(f"Path is not a file: {resolved}")
        elif resolved.stat().st_size == 0:
            issues.append("File is empty")

        return issues
