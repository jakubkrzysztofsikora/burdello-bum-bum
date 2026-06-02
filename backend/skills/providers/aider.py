"""Skill for extracting transcripts from Aider chat history Markdown files.

Handles the ``.aider.chat.history.md`` file format where conversations are
stored as Markdown with ``Human:`` / ``Assistant:`` role markers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator

from backend.skills.base import (
    ContentBlock,
    ExtractedTranscript,
    NormalizedMessage,
    SkillMetadata,
    TranscriptSkill,
)
from backend.skills.mixins import (
    MarkdownSkillMixin,
    detect_project_name_from_path,
    parse_iso_timestamp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class AiderSkill(TranscriptSkill, MarkdownSkillMixin):
    """Extract transcripts from Aider ``.aider.chat.history.md`` files.

    File layout::

        <project_root>/.aider.chat.history.md

    The file contains Markdown-formatted conversations with role markers::

        Human: <message>

        Assistant: <message>
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="aider",
            version="1.0.0",
            display_name="Aider",
            description="Parse Aider chat history from .aider.chat.history.md",
            supported_formats=[".md"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://aider.chat",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — filename is exactly ``.aider.chat.history.md``
        * ``0.5`` — filename contains ``aider.chat.history``
        * ``0.0`` — no match.
        """
        name = path.name
        if name == ".aider.chat.history.md":
            return 1.0
        if "aider.chat.history" in name:
            return 0.5
        return 0.0

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Yield :class:`ExtractedTranscript` from an Aider chat history file."""
        path = path.resolve()
        result = ExtractedTranscript(
            source_path=path,
            skill_name=self.metadata().name,
            messages=[],
            project_name=detect_project_name_from_path(path),
        )

        if not path.exists():
            result.errors.append(f"File not found: {path}")
            yield result
            return

        if path.is_dir():
            result.errors.append(f"Expected a file, got directory: {path}")
            yield result
            return

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"Cannot read file: {exc}")
            yield result
            return

        result.raw_lines = len(text.splitlines())

        # Parse the conversation
        messages = self._parse_aider_conversation(text)
        result.messages.extend(messages)
        result.parsed_lines = len(messages)

        if not result.messages:
            result.warnings.append("No messages extracted from file")

        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_source(self, path: Path) -> list[str]:
        """Return a list of issues with the source file."""
        issues: list[str] = []
        path = path.resolve()

        if not path.exists():
            return [f"Path does not exist: {path}"]

        if path.is_dir():
            return [f"Expected a file, got directory: {path}"]

        if path.suffix != ".md":
            issues.append(f"Expected .md file, got {path.suffix}")

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            issues.append(f"Cannot read file: {exc}")
            return issues

        if not text.strip():
            issues.append("File is empty")
            return issues

        # Check for expected role markers
        has_human = "Human" in text or "User" in text
        has_assistant = "Assistant" in text or "AI" in text

        if not has_human:
            issues.append("No 'Human' or 'User' markers found")
        if not has_assistant:
            issues.append("No 'Assistant' or 'AI' markers found")

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_aider_conversation(self, text: str) -> list[NormalizedMessage]:
        """Parse an Aider chat history into normalised messages.

        Aider uses ``Human:`` and ``Assistant:`` (or ``### Human`` / ``###
        Assistant``) as role markers.  Code blocks are extracted as
        ``ContentBlock(type="code")`` objects.
        """
        messages: list[NormalizedMessage] = []
        current_role: str | None = None
        current_lines: list[str] = []

        def _flush() -> None:
            nonlocal current_role, current_lines
            if current_role and current_lines:
                raw_content = "\n".join(current_lines).strip()
                if raw_content:
                    # Extract code blocks
                    content = self._extract_rich_content(raw_content)
                    messages.append(
                        NormalizedMessage(
                            role=current_role,
                            content=content,
                            metadata={},
                        ),
                    )
            current_role = None
            current_lines = []

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            detected = self.detect_role_from_line(line)

            if detected is not None:
                _flush()
                current_role = detected
                remainder = self.strip_role_marker(line)
                if remainder:
                    current_lines.append(remainder)
            else:
                if current_role is not None:
                    current_lines.append(line)

        _flush()
        return messages

    def _extract_rich_content(self, text: str) -> str | list[ContentBlock]:
        """Extract fenced code blocks from text as rich ContentBlocks.

        If no code blocks are found, returns the plain text string.
        """
        import re

        blocks: list[ContentBlock] = []
        pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
        last_end = 0

        for match in pattern.finditer(text):
            # Text before code block
            if match.start() > last_end:
                text_part = text[last_end : match.start()].strip()
                if text_part:
                    blocks.append(ContentBlock(type="text", text=text_part))

            # Code block
            language = match.group(1)
            code = match.group(2)
            blocks.append(
                ContentBlock(
                    type="code",
                    text=code,
                    language=language,
                ),
            )
            last_end = match.end()

        # Trailing text
        if last_end < len(text):
            trailing = text[last_end:].strip()
            if trailing:
                blocks.append(ContentBlock(type="text", text=trailing))

        # If no code blocks, return plain text
        if not blocks:
            return text.strip()

        # If only one text block, return as string for simplicity
        if len(blocks) == 1 and blocks[0].type == "text":
            return blocks[0].text

        return blocks
