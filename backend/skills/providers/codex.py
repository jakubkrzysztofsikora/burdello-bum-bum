"""Skill for extracting transcripts from OpenAI Codex CLI session files.

Handles the ``~/.codex/sessions/YYYY/MM/DD/*.jsonl`` format where each
line is a JSON object representing a ``session_meta``, ``response_item``,
or ``event_msg`` record from a Codex CLI session.
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
# Codex record type constants
# ---------------------------------------------------------------------------

_CODEX_RECORD_TYPES: set[str] = {
    "session_meta",
    "response_item",
    "event_msg",
    "command",
    "output",
    "input",
    "response",
}

_CODEX_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "human": "user",
    "assistant": "assistant",
    "system": "system",
    "developer": "system",
    "tool": "tool",
}


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class CodexSkill(TranscriptSkill, JSONLSkillMixin):
    """Extract transcripts from OpenAI Codex CLI ``.jsonl`` session logs.

    Directory layout::

        ~/.codex/sessions/YYYY/MM/DD/
            <session_id>.jsonl

    Each line is a JSON object.  Known ``type`` values:

    * ``session_meta`` — session metadata (model, cwd, timestamp).
    * ``response_item`` — assistant turn (may contain reasoning, code).
    * ``event_msg`` / ``input`` — user message or event.
    * ``command`` / ``output`` — terminal command and its output.
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="codex",
            version="1.0.0",
            display_name="OpenAI Codex CLI",
            description="Parse Codex CLI JSONL session logs from "
                        "~/.codex/sessions/YYYY/MM/DD/*.jsonl",
            supported_formats=[".jsonl", ".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://github.com/openai/codex",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``.codex/sessions/``
        * ``0.3`` — path contains ``.codex/`` but not the sessions sub-dir.
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if ".codex" not in parts:
            return 0.0
        idx = parts.index(".codex")
        if idx + 2 < len(parts) and parts[idx + 1] == "sessions":
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
        """Yield :class:`ExtractedTranscript` objects from a Codex JSONL file."""
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
            for jsonl_file in sorted(path.rglob("*.jsonl")):
                yield from self.extract_transcripts(jsonl_file, **options)
            return

        current_model: str | None = None
        session_metadata: dict[str, Any] = {}

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            rec_type = record.get("type", "")
            if isinstance(rec_type, str):
                rec_type = rec_type.lower()
            else:
                rec_type = ""

            # Accumulate session metadata
            if rec_type == "session_meta":
                session_metadata.update(record)
                if not current_model:
                    current_model = record.get("model") or record.get("model_name")
                if not result.session_id:
                    result.session_id = record.get("session_id") or record.get("id")
                continue

            # Extract role and content based on record type
            role = self._extract_role(record, rec_type)
            timestamp = self._extract_timestamp(record)
            content = self._extract_content(record, rec_type)

            if content is None:
                result.warnings.append(
                    f"Line {result.raw_lines}: could not extract content "
                    f"(type={rec_type})"
                )
                continue

            msg_type = self._classify_message_type(record, rec_type)

            norm_msg = NormalizedMessage(
                role=role,
                content=content,
                timestamp=timestamp,
                message_type=msg_type,
                model=current_model,
                metadata={k: v for k, v in record.items() if k not in {
                    "type", "role", "content", "timestamp", "created_at",
                    "model", "model_name", "session_id", "message",
                }},
            )
            result.messages.append(norm_msg)
            result.parsed_lines += 1

        result.model = current_model
        result.metadata = session_metadata
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
            jsonl_files = list(path.rglob("*.jsonl"))
            if not jsonl_files:
                issues.append(f"No .jsonl files found under: {path}")
            return issues

        if path.suffix not in (".jsonl", ".json"):
            issues.append(f"Expected .jsonl or .json, got {path.suffix}")

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
        elif "type" not in first:
            issues.append(
                "First line lacks a 'type' field — may not be a Codex session file"
            )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_role(self, record: dict[str, Any], rec_type: str) -> str:
        """Determine the speaker role for a Codex record."""
        raw_role = record.get("role", "")
        if isinstance(raw_role, str):
            mapped = _CODEX_ROLE_MAP.get(raw_role.lower())
            if mapped:
                return mapped

        # Infer from record type
        type_role_map: dict[str, str] = {
            "event_msg": "user",
            "input": "user",
            "command": "user",
            "response_item": "assistant",
            "response": "assistant",
            "output": "assistant",
        }
        return type_role_map.get(rec_type, "assistant")

    def _extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Pull a timestamp from a Codex record."""
        for key in ("timestamp", "created_at", "ts", "time", "date"):
            val = record.get(key)
            if val is not None:
                parsed = parse_iso_timestamp(val)
                if parsed:
                    return parsed
        return None

    def _extract_content(
        self,
        record: dict[str, Any],
        rec_type: str,
    ) -> str | list[ContentBlock] | None:
        """Convert the raw content into a normalised form."""
        content = record.get("content")
        message = record.get("message")

        # Use 'message' field as content fallback
        if content is None and message is not None:
            content = message

        # Handle reasoning / thinking blocks
        reasoning = record.get("reasoning") or record.get("thinking")

        # --- Structured content (list of blocks) -----------------------
        if isinstance(content, list):
            blocks: list[ContentBlock] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "text")
                    if item_type in ("text", "input_text"):
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                    elif item_type in ("code", "input_code", "file"):
                        blocks.append(
                            ContentBlock(
                                type="code",
                                text=item.get("text", "") or item.get("code", ""),
                                language=item.get("language"),
                            ),
                        )
                    elif item_type in ("tool_use", "tool_call"):
                        blocks.append(
                            ContentBlock(
                                type="tool_use",
                                text=item.get("text", ""),
                                tool_name=item.get("name")
                                or item.get("tool_name"),
                                tool_input=item.get("input")
                                or item.get("arguments", {}),
                            ),
                        )
                    elif item_type in ("tool_result", "tool_output"):
                        result_text = item.get("content", "") or item.get("output", "")
                        if not isinstance(result_text, str):
                            result_text = str(result_text)
                        blocks.append(
                            ContentBlock(
                                type="tool_result",
                                text=result_text,
                            ),
                        )
                    else:
                        blocks.append(
                            ContentBlock(
                                type="text",
                                text=item.get("text", "")
                                or str(item),
                            ),
                        )
                elif isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
            # Append reasoning as a separate thinking block
            if reasoning:
                blocks.append(
                    ContentBlock(type="text", text=f"[Reasoning] {reasoning}"),
                )
            return blocks if blocks else None

        # --- Dict content ----------------------------------------------
        if isinstance(content, dict):
            text = content.get("text", "") or content.get("message", "")
            code = content.get("code", "")
            if code:
                blocks = []
                if text:
                    blocks.append(ContentBlock(type="text", text=text))
                blocks.append(
                    ContentBlock(type="code", text=code, language=content.get("language")),
                )
                return blocks
            return text or __import__("json").dumps(content)

        # --- String content --------------------------------------------
        if isinstance(content, str):
            if reasoning:
                return [
                    ContentBlock(type="text", text=content),
                    ContentBlock(type="text", text=f"[Reasoning] {reasoning}"),
                ]
            return content

        # --- Command / output special handling -------------------------
        if rec_type == "command":
            cmd = record.get("command") or record.get("cmd", "")
            return f"$ {cmd}" if isinstance(cmd, str) else str(cmd)

        if rec_type == "output":
            output = record.get("output", "") or record.get("stdout", "")
            return output if isinstance(output, str) else str(output)

        # Fallback: try any string-valued field
        for key in ("text", "body", "data", "value"):
            val = record.get(key)
            if isinstance(val, str):
                return val

        return None

    def _classify_message_type(self, record: dict[str, Any], rec_type: str) -> str:
        """Classify the semantic message type."""
        if rec_type in ("command", "input", "event_msg"):
            return "message"
        if rec_type in ("response_item", "response"):
            return "message"
        if rec_type == "output":
            return "tool_result"
        if rec_type == "session_meta":
            return "summary"
        return "message"
