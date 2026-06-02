"""Generic fallback skill for transcript extraction.

Handles any ``.jsonl``, ``.md``, or ``.txt`` file with heuristic parsing.
This skill is the catch-all of last resort — it tries to make sense of
unknown file formats by looking for common conversation patterns.
"""

from __future__ import annotations

import json
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
    JSONLSkillMixin,
    MarkdownSkillMixin,
    detect_project_name_from_path,
    parse_iso_timestamp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class GenericSkill(TranscriptSkill, JSONLSkillMixin, MarkdownSkillMixin):
    """Generic fallback skill for any ``.jsonl``, ``.md``, or ``.txt`` file.

    Uses heuristic pattern matching to identify conversations in unknown
    formats.  Tries JSONL first (array of message objects), then Markdown
    (role markers), then plain text (line-by-line with best-effort role
    detection).

    This skill should always be registered **last** in the registry so that
    more specific skills take precedence.
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="generic",
            version="1.0.0",
            display_name="Generic Fallback",
            description="Heuristic parser for any .jsonl, .md, or .txt file",
            supported_formats=[".jsonl", ".md", ".txt"],
            priority=999,  # Lowest priority — always last resort
            enabled=True,
            author="Burdello Bum-Bum",
            url="",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``0.1`` — file has a generic extension (``.jsonl``, ``.md``, ``.txt``).
        * ``0.0`` — no match.
        """
        if path.suffix in (".jsonl", ".md", ".txt"):
            return 0.1
        return 0.0

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Yield :class:`ExtractedTranscript` using heuristic parsing."""
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
            for ext in ("*.jsonl", "*.md", "*.txt"):
                for file in sorted(path.glob(ext)):
                    yield from self.extract_transcripts(file, **options)
            return

        # Dispatch based on extension
        if path.suffix == ".jsonl":
            yield from self._parse_jsonl(path, result)
        elif path.suffix == ".md":
            yield from self._parse_markdown(path, result)
        elif path.suffix == ".txt":
            yield from self._parse_text(path, result)
        else:
            result.warnings.append(f"Unsupported extension: {path.suffix}")
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
            has_files = bool(
                list(path.glob("*.jsonl"))
                or list(path.glob("*.md"))
                or list(path.glob("*.txt"))
            )
            if not has_files:
                issues.append(
                    f"No .jsonl, .md, or .txt files found under: {path}"
                )
            return issues

        if path.suffix not in (".jsonl", ".md", ".txt"):
            issues.append(
                f"Expected .jsonl, .md, or .txt, got {path.suffix}"
            )

        if path.stat().st_size == 0:
            issues.append("File is empty")

        return issues

    # ------------------------------------------------------------------
    # JSONL parser (heuristic)
    # ------------------------------------------------------------------

    def _parse_jsonl(
        self,
        path: Path,
        result: ExtractedTranscript,
    ) -> Iterator[ExtractedTranscript]:
        """Heuristic JSONL parsing — look for message-like objects."""
        current_model: str | None = None

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            if not isinstance(record, dict):
                continue

            # Try to extract role
            role = self._heuristic_extract_role(record)
            content = self._heuristic_extract_content(record)
            timestamp = self._heuristic_extract_timestamp(record)
            model = record.get("model") or record.get("model_name")
            if model:
                current_model = model

            if content is None:
                continue

            result.messages.append(
                NormalizedMessage(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    model=current_model,
                ),
            )
            result.parsed_lines += 1

        result.model = current_model
        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    # ------------------------------------------------------------------
    # Markdown parser (heuristic)
    # ------------------------------------------------------------------

    def _parse_markdown(
        self,
        path: Path,
        result: ExtractedTranscript,
    ) -> Iterator[ExtractedTranscript]:
        """Heuristic Markdown parsing using role markers."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"Cannot read file: {exc}")
            yield result
            return

        result.raw_lines = len(text.splitlines())
        messages = self.parse_markdown_conversation(text, source_path=path)
        result.messages.extend(messages)
        result.parsed_lines = len(messages)

        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    # ------------------------------------------------------------------
    # Plain text parser (heuristic)
    # ------------------------------------------------------------------

    def _parse_text(
        self,
        path: Path,
        result: ExtractedTranscript,
    ) -> Iterator[ExtractedTranscript]:
        """Heuristic plain-text parsing — alternating user/assistant lines."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            result.errors.append(f"Cannot read file: {exc}")
            yield result
            return

        result.raw_lines = len(lines)

        # Try to detect alternating roles
        # Strategy: look for prefix patterns, then fall back to alternating
        role_patterns: list[tuple[str, str]] = [
            (">>", "user"),
            ("<<", "assistant"),
            ("USER:", "user"),
            ("ASSISTANT:", "assistant"),
            ("Q:", "user"),
            ("A:", "assistant"),
        ]

        messages: list[NormalizedMessage] = []
        current_role: str | None = None
        current_lines: list[str] = []
        line_idx = 0

        def _flush() -> None:
            nonlocal current_role, current_lines
            if current_role and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    messages.append(
                        NormalizedMessage(
                            role=current_role,
                            content=content,
                            metadata={"line_index": line_idx},
                        ),
                    )
            current_role = None
            current_lines = []

        for i, raw_line in enumerate(lines):
            line_idx = i
            stripped = raw_line.strip()
            if not stripped:
                continue

            # Check for role prefix
            detected_role: str | None = None
            for prefix, role in role_patterns:
                if stripped.upper().startswith(prefix):
                    detected_role = role
                    stripped = stripped[len(prefix) :].strip()
                    break

            if detected_role is not None:
                _flush()
                current_role = detected_role
                current_lines.append(stripped)
            elif current_role is not None:
                current_lines.append(raw_line)
            else:
                # No role detected yet — try to infer from line structure
                # If it looks like a prompt marker, treat as user
                if stripped.endswith("?") or stripped.endswith(":"):
                    current_role = "user"
                    current_lines.append(stripped)

        _flush()

        # If no messages with prefixes found, try alternating lines
        if not messages:
            non_empty = [l.strip() for l in lines if l.strip()]
            for i, line in enumerate(non_empty):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append(
                    NormalizedMessage(
                        role=role,
                        content=line,
                        metadata={"line_index": i},
                    ),
                )

        result.messages.extend(messages)
        result.parsed_lines = len(messages)

        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    # ------------------------------------------------------------------
    # Heuristic extractors
    # ------------------------------------------------------------------

    def _heuristic_extract_role(self, record: dict[str, Any]) -> str:
        """Best-effort role extraction from a dict."""
        for key in ("role", "sender", "author", "speaker", "from", "user"):
            val = record.get(key)
            if isinstance(val, str):
                val_lower = val.lower()
                if val_lower in ("human", "user"):
                    return "user"
                if val_lower in ("ai", "assistant", "bot", "model"):
                    return "assistant"
                if val_lower == "system":
                    return "system"
                if val_lower == "tool":
                    return "tool"
        # Check type field
        type_val = record.get("type", "")
        if isinstance(type_val, str):
            type_lower = type_val.lower()
            if type_lower in ("user_message", "input", "prompt", "query"):
                return "user"
            if type_lower in ("assistant_message", "response", "output", "reply"):
                return "assistant"
        return "assistant"  # default

    def _heuristic_extract_content(
        self,
        record: dict[str, Any],
    ) -> str | list[ContentBlock] | None:
        """Best-effort content extraction from a dict."""
        for key in ("content", "text", "message", "body", "value", "data", "prompt"):
            val = record.get(key)
            if val is not None:
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    return val.get("text", "") or json.dumps(val)
                if isinstance(val, list):
                    texts: list[str] = []
                    for item in val:
                        if isinstance(item, str):
                            texts.append(item)
                        elif isinstance(item, dict):
                            texts.append(item.get("text", "") or str(item))
                    return "\n".join(texts) if texts else None
                return str(val)
        return None

    def _heuristic_extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Best-effort timestamp extraction from a dict."""
        for key in ("timestamp", "created_at", "ts", "time", "date", "datetime"):
            val = record.get(key)
            if val is not None:
                parsed = parse_iso_timestamp(val)
                if parsed:
                    return parsed
        return None
