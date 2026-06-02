"""Skill for extracting transcripts from Claude Code JSONL files.

Handles the ``~/.claude/projects/<project>/*.jsonl`` format where each
line is a JSON object representing a message, tool_use, tool_result,
thinking block, or summary from a Claude Code session.
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
    JSONLSkillMixin,
    detect_project_name_from_path,
    parse_iso_timestamp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role mapping
# ---------------------------------------------------------------------------

_CLAUDE_ROLE_MAP: dict[str, str] = {
    "human": "user",
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
}

# Message types emitted by Claude Code
_CLAUDE_MESSAGE_TYPES: set[str] = {
    "message",
    "tool_use",
    "tool_result",
    "thinking",
    "summary",
}


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class ClaudeCodeSkill(TranscriptSkill, JSONLSkillMixin):
    """Extract transcripts from Claude Code ``.jsonl`` conversation logs.

    Directory layout::

        ~/.claude/projects/<project_name>/
            <session_id>.jsonl

    Each line is a JSON object with fields such as:

    * ``type`` — ``message``, ``tool_use``, ``tool_result``, ``thinking``,
      ``summary``
    * ``role`` — ``human``, ``assistant``, ``system``
    * ``content`` — string or array of blocks
    * ``timestamp`` / ``created_at`` — ISO-8601 or Unix epoch
    * ``model`` — model identifier string
    * ``session_id`` — conversation session UUID
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="claude_code",
            version="1.0.0",
            display_name="Claude Code",
            description="Parse Claude Code JSONL conversation logs from "
                        "~/.claude/projects/<project>/*.jsonl",
            supported_formats=[".jsonl", ".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://docs.anthropic.com/claude-code",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``.claude/projects/``
        * ``0.3`` — path contains ``.claude/`` but not the projects sub-dir.
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if ".claude" not in parts:
            return 0.0
        idx = parts.index(".claude")
        if idx + 2 < len(parts) and parts[idx + 1] == "projects":
            return 1.0
        return 0.3

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Yield a single :class:`ExtractedTranscript` from a Claude Code JSONL file."""
        path = path.resolve()
        result = ExtractedTranscript(
            source_type="claude_code",
            source_path=path,
            skill_name="claude_code",
            project_name=detect_project_name_from_path(path),
        )

        if not path.exists():
            result.errors.append(f"File not found: {path}")
            yield result
            return

        if path.is_dir():
            # When given a directory, process every .jsonl file inside
            for jsonl_file in sorted(path.glob("*.jsonl")):
                yield from self.extract_transcripts(jsonl_file, **options)
            return

        current_model: str | None = None
        current_session: str | None = None
        message_index = 0

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            # Claude Code wraps the real message under a "message" key:
            #   {"type":"user","message":{"role":...,"content":...}}
            # Flatten it so role/content are reachable by the helpers below
            # (message fields win; top-level type/timestamp/uuid are kept).
            inner = record.get("message")
            if isinstance(inner, dict):
                record = {**record, **inner}

            msg_type = record.get("type", "message")
            if msg_type not in _CLAUDE_MESSAGE_TYPES:
                msg_type = "message"

            speaker = self._extract_speaker(record)
            timestamp = self._extract_timestamp(record)
            model = record.get("model") or record.get("model_name")
            session_id = record.get("session_id")
            if model:
                current_model = model
            if session_id:
                current_session = session_id

            content = self._extract_content(record, msg_type)
            if content is None:
                result.warnings.append(
                    f"Line {result.raw_lines}: could not extract content "
                    f"(type={msg_type})"
                )
                continue

            norm_msg = NormalizedMessage(
                speaker=speaker,
                content=content,
                sequence=message_index,
                timestamp=timestamp,
                message_type=msg_type,
                model=current_model,
                metadata={k: v for k, v in record.items() if k not in {
                    "type", "role", "content", "timestamp", "created_at",
                    "model", "model_name", "session_id",
                }},
            )
            result.messages.append(norm_msg)
            result.parsed_lines += 1
            message_index += 1

        result.model = current_model
        result.session_id = current_session
        if result.messages:
            result.started_at = str(result.messages[0].timestamp) if result.messages[0].timestamp else None
            result.ended_at = str(result.messages[-1].timestamp) if result.messages[-1].timestamp else None
            result.raw_text = self._concatenate_raw_text(result.messages)

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
            jsonl_files = list(path.glob("*.jsonl"))
            if not jsonl_files:
                issues.append(f"No .jsonl files found in directory: {path}")
            return issues

        if path.suffix not in (".jsonl", ".json"):
            issues.append(f"Expected .jsonl or .json, got {path.suffix}")

        # Try to parse at least the first line
        first_lines: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    stripped = raw.strip()
                    if stripped:
                        first_lines.append(__import__("json").loads(stripped))
                        break
        except Exception as exc:
            issues.append(f"Cannot read/parse file: {exc}")
            return issues

        if not first_lines:
            issues.append("File is empty")
            return issues

        first = first_lines[0]
        if not isinstance(first, dict):
            issues.append(f"First line is not a JSON object (got {type(first).__name__})")
        elif "type" not in first and "role" not in first:
            issues.append(
                "First line lacks expected fields (type, role) — "
                "may not be a Claude Code conversation file"
            )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_speaker(self, record: dict[str, Any]) -> str:
        """Map the Claude ``role`` field to a normalised speaker slug."""
        raw_role = record.get("role", "")
        if isinstance(raw_role, str):
            return _CLAUDE_ROLE_MAP.get(raw_role.lower(), "assistant")
        return "assistant"

    def _extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Pull a timestamp from the record, trying multiple keys."""
        for key in ("timestamp", "created_at", "ts", "time"):
            val = record.get(key)
            if val is not None:
                parsed = parse_iso_timestamp(val)
                if parsed:
                    return parsed
        return None

    def _extract_content(
        self,
        record: dict[str, Any],
        msg_type: str,
    ) -> str | list[ContentBlock] | None:
        """Convert the raw ``content`` field into a normalised form."""
        content = record.get("content")

        # --- Tool use --------------------------------------------------
        if msg_type == "tool_use":
            tool_name = record.get("tool_name") or record.get("name", "")
            tool_input = record.get("tool_input") or record.get("input", {})
            tool_use_id = record.get("tool_use_id") or record.get("id", "")
            text = ""
            if isinstance(content, str):
                text = content
            return [
                ContentBlock(
                    type="tool_use",
                    text=text or f"Using tool: {tool_name}",
                    tool_name=tool_name if isinstance(tool_name, str) else None,
                    tool_input=tool_input if isinstance(tool_input, dict) else None,
                    tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                ),
            ]

        # --- Tool result -----------------------------------------------
        if msg_type == "tool_result":
            tool_use_id = record.get("tool_use_id") or record.get("id", "")
            result_text = ""
            if isinstance(content, str):
                result_text = content
            elif isinstance(content, dict):
                result_text = content.get("output", "") or content.get("result", "")
                if not result_text:
                    result_text = __import__("json").dumps(content)
            elif content is not None:
                result_text = str(content)
            if not result_text:
                result_text = record.get("result", "") or record.get("output", "")
            return [
                ContentBlock(
                    type="tool_result",
                    text=result_text,
                    tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                ),
            ]

        # --- Array of blocks -------------------------------------------
        if isinstance(content, list):
            blocks: list[ContentBlock] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "text")
                    if item_type in ("tool_use", "tool_use_block"):
                        blocks.append(
                            ContentBlock(
                                type="tool_use",
                                text=item.get("text", ""),
                                tool_name=item.get("name")
                                or item.get("tool_name"),
                                tool_input=item.get("input")
                                or item.get("tool_input"),
                                tool_use_id=item.get("id")
                                or item.get("tool_use_id"),
                            ),
                        )
                    elif item_type in ("tool_result", "tool_result_block"):
                        blocks.append(
                            ContentBlock(
                                type="tool_result",
                                text=str(item.get("content", "")),
                                tool_use_id=item.get("tool_use_id")
                                or item.get("id"),
                            ),
                        )
                    elif item_type == "image":
                        blocks.append(
                            ContentBlock(
                                type="image",
                                text=item.get("text", ""),
                                mime_type=item.get("mime_type")
                                or item.get("media_type"),
                            ),
                        )
                    else:
                        blocks.append(
                            ContentBlock(
                                type="text",
                                text=item.get("text", ""),
                            ),
                        )
                elif isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
            return blocks if blocks else None

        # --- Plain string ----------------------------------------------
        if isinstance(content, str):
            return content

        # --- Dict fallback ---------------------------------------------
        if isinstance(content, dict):
            return content.get("text", "") or __import__("json").dumps(content)

        if content is not None:
            return str(content)

        # No content at all — for thinking/summary this is okay
        if msg_type in ("thinking", "summary"):
            return record.get("thinking", "") or record.get("summary", "") or ""

        return None

    @staticmethod
    def _concatenate_raw_text(messages: list[NormalizedMessage]) -> str:
        """Join all message contents into a single raw text string."""
        parts: list[str] = []
        for m in messages:
            if isinstance(m.content, str):
                parts.append(f"{m.speaker or 'unknown'}: {m.content}")
            elif isinstance(m.content, list):
                text_parts = [b.text for b in m.content if hasattr(b, "text")]
                parts.append(f"{m.speaker or 'unknown'}: {' '.join(text_parts)}")
            else:
                parts.append(f"{m.speaker or 'unknown'}: {str(m.content)}")
        return "\n\n".join(parts)
