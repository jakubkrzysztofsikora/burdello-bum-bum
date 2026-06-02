"""Skill for extracting transcripts from Moonshot AI Kimi session files.

Handles the ``~/.kimi/sessions/<group>/<session>/wire.jsonl`` format where
each line is a JSON object representing events such as ``StatusUpdate``,
``TextPart``, ``ThinkPart``, ``ToolCall``, and ``ToolResult``.
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
# Kimi event type constants
# ---------------------------------------------------------------------------

_KIMI_EVENT_TYPES: set[str] = {
    "status_update",
    "text_part",
    "think_part",
    "tool_call",
    "tool_result",
    "message",
    "user_message",
    "assistant_message",
    "system_message",
    "error",
}

_KIMI_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "human": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
}


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class KimiSkill(TranscriptSkill, JSONLSkillMixin):
    """Extract transcripts from Kimi CLI ``wire.jsonl`` session logs.

    Directory layout::

        ~/.kimi/sessions/<group>/<session>/
            wire.jsonl

    Each line is a JSON event.  Known ``event_type`` / ``type`` values:

    * ``StatusUpdate`` — connection / session status changes.
    * ``TextPart`` — text fragment from the assistant.
    * ``ThinkPart`` — reasoning / thinking block.
    * ``ToolCall`` — tool invocation by the assistant.
    * ``ToolResult`` — result returned from a tool.
    * ``user_message`` / ``assistant_message`` — complete messages.
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="kimi",
            version="1.0.0",
            display_name="Moonshot Kimi",
            description="Parse Kimi CLI JSONL session logs from "
                        "~/.kimi/sessions/<group>/<session>/wire.jsonl",
            supported_formats=[".jsonl", ".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://github.com/MoonshotAI/Kimi-CLI",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``.kimi/sessions/``
        * ``0.3`` — path contains ``.kimi/`` but not the sessions sub-dir.
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if ".kimi" not in parts:
            return 0.0
        idx = parts.index(".kimi")
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
        """Yield :class:`ExtractedTranscript` from a Kimi ``wire.jsonl`` file."""
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
            # Look for wire.jsonl inside session dirs
            for wire_file in sorted(path.rglob("wire.jsonl")):
                yield from self.extract_transcripts(wire_file, **options)
            return

        current_model: str | None = None
        buffer_text_parts: list[str] = []
        buffer_think_parts: list[str] = []
        current_role: str = "assistant"
        current_timestamp: str | None = None
        current_metadata: dict[str, Any] = {}

        def _flush_buffered() -> None:
            """Flush accumulated text/think parts as a single message."""
            nonlocal buffer_text_parts, buffer_think_parts
            texts = []
            if buffer_text_parts:
                texts.append("".join(buffer_text_parts))
            if buffer_think_parts:
                texts.append("[Thinking] " + "".join(buffer_think_parts))
            if texts:
                content = "\n".join(texts)
                result.messages.append(
                    NormalizedMessage(
                        role=current_role,
                        content=content,
                        timestamp=current_timestamp,
                        model=current_model,
                        metadata=dict(current_metadata),
                    ),
                )
                result.parsed_lines += 1
            buffer_text_parts = []
            buffer_think_parts = []

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            event_type = self._extract_event_type(record)
            timestamp = self._extract_timestamp(record)
            if timestamp:
                current_timestamp = timestamp

            # Update model if present
            model = record.get("model") or record.get("model_name")
            if model:
                current_model = model

            # Handle different event types
            if event_type in ("text_part",):
                text = record.get("text", "") or record.get("content", "")
                if isinstance(text, str):
                    buffer_text_parts.append(text)
                continue

            if event_type in ("think_part", "thinking"):
                text = record.get("text", "") or record.get("thinking", "")
                if isinstance(text, str):
                    buffer_think_parts.append(text)
                continue

            # For non-buffered events, flush any pending text first
            _flush_buffered()

            if event_type == "status_update":
                # Status updates don't produce messages but may carry metadata
                status = record.get("status") or record.get("state", "")
                if status and isinstance(status, str):
                    result.metadata["last_status"] = status
                continue

            if event_type in ("tool_call",):
                tool_name = record.get("tool_name") or record.get("name", "")
                tool_input = record.get("tool_input") or record.get("arguments", {})
                tool_use_id = record.get("tool_use_id") or record.get("id", "")
                tool_text = record.get("text", "")
                result.messages.append(
                    NormalizedMessage(
                        role="assistant",
                        content=[
                            ContentBlock(
                                type="tool_use",
                                text=tool_text if isinstance(tool_text, str) else f"Tool: {tool_name}",
                                tool_name=tool_name if isinstance(tool_name, str) else None,
                                tool_input=tool_input if isinstance(tool_input, dict) else None,
                                tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                            ),
                        ],
                        timestamp=current_timestamp,
                        message_type="tool_use",
                        model=current_model,
                    ),
                )
                result.parsed_lines += 1
                continue

            if event_type in ("tool_result",):
                tool_use_id = record.get("tool_use_id") or record.get("id", "")
                result_text = record.get("result", "") or record.get("output", "") or record.get("text", "")
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                result.messages.append(
                    NormalizedMessage(
                        role="tool",
                        content=[
                            ContentBlock(
                                type="tool_result",
                                text=result_text,
                                tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                            ),
                        ],
                        timestamp=current_timestamp,
                        message_type="tool_result",
                        model=current_model,
                    ),
                )
                result.parsed_lines += 1
                continue

            if event_type in ("user_message", "message"):
                role = self._extract_role(record)
                content = self._extract_content(record)
                if content is not None:
                    result.messages.append(
                        NormalizedMessage(
                            role=role,
                            content=content,
                            timestamp=current_timestamp,
                            message_type="message",
                            model=current_model,
                        ),
                    )
                    result.parsed_lines += 1
                continue

            if event_type in ("assistant_message",):
                content = self._extract_content(record)
                if content is not None:
                    result.messages.append(
                        NormalizedMessage(
                            role="assistant",
                            content=content,
                            timestamp=current_timestamp,
                            message_type="message",
                            model=current_model,
                        ),
                    )
                    result.parsed_lines += 1
                continue

            # Fallback: try to extract content from unknown event types
            content = self._extract_content(record)
            if content is not None:
                role = self._extract_role(record)
                result.messages.append(
                    NormalizedMessage(
                        role=role,
                        content=content,
                        timestamp=current_timestamp,
                        model=current_model,
                        metadata={"event_type": event_type},
                    ),
                )
                result.parsed_lines += 1
            else:
                result.warnings.append(
                    f"Line {result.raw_lines}: unhandled event type '{event_type}'"
                )

        # Flush any remaining buffered text parts
        _flush_buffered()

        result.model = current_model
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
            wire_files = list(path.rglob("wire.jsonl"))
            if not wire_files:
                issues.append(f"No wire.jsonl files found under: {path}")
            return issues

        if path.name != "wire.jsonl" and path.suffix not in (".jsonl", ".json"):
            issues.append(f"Expected wire.jsonl or .jsonl, got {path.name}")

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
        elif "event_type" not in first and "type" not in first:
            issues.append(
                "First line lacks 'event_type' or 'type' field — "
                "may not be a Kimi wire file"
            )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_event_type(self, record: dict[str, Any]) -> str:
        """Extract and normalise the event type from a Kimi record."""
        for key in ("event_type", "type", "event", "kind"):
            val = record.get(key)
            if isinstance(val, str):
                return val.lower().replace(" ", "_")
        return ""

    def _extract_role(self, record: dict[str, Any]) -> str:
        """Map the Kimi ``role`` field to a normalised role slug."""
        raw_role = record.get("role", "")
        if isinstance(raw_role, str):
            mapped = _KIMI_ROLE_MAP.get(raw_role.lower())
            if mapped:
                return mapped
        # Infer from event type
        event_type = self._extract_event_type(record)
        if event_type in ("user_message", "text_input"):
            return "user"
        if event_type in ("assistant_message", "text_part", "think_part"):
            return "assistant"
        if event_type in ("tool_call",):
            return "assistant"
        if event_type in ("tool_result",):
            return "tool"
        return "assistant"

    def _extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Pull a timestamp from a Kimi record."""
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
    ) -> str | list[ContentBlock] | None:
        """Convert raw content into a normalised form."""
        content = record.get("content")
        text = record.get("text")

        # Prefer 'content', fall back to 'text'
        if content is None and text is not None:
            content = text

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            blocks: list[ContentBlock] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "text")
                    if item_type in ("text", "input_text"):
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                    elif item_type == "code":
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
                                tool_name=item.get("name") or item.get("tool_name"),
                                tool_input=item.get("input") or item.get("arguments", {}),
                            ),
                        )
                    elif item_type in ("tool_result",):
                        result_text = item.get("content", "") or item.get("output", "")
                        if not isinstance(result_text, str):
                            result_text = str(result_text)
                        blocks.append(
                            ContentBlock(type="tool_result", text=result_text),
                        )
                    else:
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                elif isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
            return blocks if blocks else None

        if isinstance(content, dict):
            return content.get("text", "") or __import__("json").dumps(content)

        if content is not None:
            return str(content)

        # Fallback: try 'message' field
        message = record.get("message")
        if isinstance(message, str):
            return message

        return None
