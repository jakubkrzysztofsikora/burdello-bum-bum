"""Skill for extracting transcripts from OpenClaw / AutoClaw session files.

Handles the ``~/.openclaw-autoclaw/agents/main/sessions/<uuid>.jsonl`` format
where each line is a JSON event such as ``session``, ``message``,
``toolCall``, and ``toolResult``.
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
from backend.skills.mixins import JSONLSkillMixin, parse_iso_timestamp

logger = logging.getLogger(__name__)


class OpenclawSkill(TranscriptSkill, JSONLSkillMixin):
    """Extract transcripts from OpenClaw / AutoClaw JSONL session logs."""

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="openclaw",
            version="1.0.0",
            display_name="OpenClaw / AutoClaw",
            description="Parse OpenClaw/AutoClaw JSONL session logs from "
                        "~/.openclaw*/agents/main/sessions/*.jsonl",
            supported_formats=[".jsonl", ".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://github.com/jakubkrzysztofsikora/burdello-bum-bum",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``.openclaw`` and ``/agents/main/sessions/``.
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if not any(".openclaw" in p for p in parts):
            return 0.0
        if "/agents/main/sessions/" in str(path):
            return 1.0
        return 0.3

    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Yield :class:`ExtractedTranscript` from an OpenClaw session file."""
        path = path.resolve()
        result = ExtractedTranscript(
            source_type="openclaw",
            source_path=path,
            skill_name="openclaw",
            project_name=None,
        )

        if not path.exists():
            result.errors.append(f"File not found: {path}")
            yield result
            return

        if path.is_dir():
            for session_file in sorted(path.rglob("*.jsonl")):
                yield from self.extract_transcripts(session_file, **options)
            return

        session_cwd: str | None = None
        current_model: str | None = None
        message_index = 0

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            record_type = str(record.get("type", "")).lower()
            timestamp = self._extract_timestamp(record)

            if record_type == "session":
                session_cwd = record.get("cwd") or session_cwd
                continue

            if record_type == "model_change":
                current_model = record.get("modelId") or current_model
                continue

            if record_type == "message":
                message = record.get("message") or {}
                speaker = self._extract_speaker(message)
                content = self._extract_content(message.get("content"))
                if content is not None:
                    result.messages.append(
                        NormalizedMessage(
                            speaker=speaker,
                            content=content,
                            sequence=message_index,
                            timestamp=timestamp,
                            message_type="message",
                            model=current_model,
                        ),
                    )
                    result.parsed_lines += 1
                    message_index += 1
                continue

            if record_type == "toolcall":
                tool_name = record.get("name") or record.get("toolName", "")
                tool_input = record.get("arguments") or record.get("input", {})
                tool_use_id = record.get("id", "")
                result.messages.append(
                    NormalizedMessage(
                        speaker="assistant",
                        content=[
                            ContentBlock(
                                type="tool_use",
                                text=f"Tool: {tool_name}",
                                tool_name=tool_name if isinstance(tool_name, str) else None,
                                tool_input=tool_input if isinstance(tool_input, dict) else None,
                                tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                            ),
                        ],
                        sequence=message_index,
                        timestamp=timestamp,
                        message_type="tool_use",
                        model=current_model,
                    ),
                )
                result.parsed_lines += 1
                message_index += 1
                continue

            if record_type == "toolresult":
                tool_use_id = record.get("toolCallId") or record.get("id", "")
                result_text = self._extract_content(record.get("content"))
                if not isinstance(result_text, str):
                    result_text = str(result_text) if result_text is not None else ""
                result.messages.append(
                    NormalizedMessage(
                        speaker="tool",
                        content=[
                            ContentBlock(
                                type="tool_result",
                                text=result_text,
                                tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
                            ),
                        ],
                        sequence=message_index,
                        timestamp=timestamp,
                        message_type="tool_result",
                        model=current_model,
                    ),
                )
                result.parsed_lines += 1
                message_index += 1
                continue

        if session_cwd:
            result.metadata["cwd"] = session_cwd
        result.model = current_model
        if result.messages:
            result.started_at = str(result.messages[0].timestamp) if result.messages[0].timestamp else None
            result.ended_at = str(result.messages[-1].timestamp) if result.messages[-1].timestamp else None
            result.raw_text = self._concatenate_raw_text(result.messages)

        yield result

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
            issues.append(f"Expected .jsonl or .json, got {path.name}")

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
            issues.append("First line lacks 'type' field — may not be an OpenClaw session file")

        return issues

    def _extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Pull a timestamp from a record."""
        for key in ("timestamp", "created_at", "ts", "time"):
            val = record.get(key)
            if val is not None:
                parsed = parse_iso_timestamp(val)
                if parsed:
                    return parsed
        return None

    def _extract_speaker(self, message: dict[str, Any]) -> str:
        """Map the message role to a normalised speaker slug."""
        role = str(message.get("role", "")).lower()
        if role in ("user", "human"):
            return "user"
        if role in ("assistant", "ai"):
            return "assistant"
        if role == "system":
            return "system"
        if role == "tool":
            return "tool"
        return "assistant"

    def _extract_content(
        self,
        content: Any,
    ) -> str | list[ContentBlock] | None:
        """Convert raw content into a normalised form."""
        if content is None:
            return None

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            blocks: list[ContentBlock] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "text")
                    if item_type in ("text", "input_text"):
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                    elif item_type == "thinking":
                        blocks.append(ContentBlock(type="text", text=f"[Thinking] {item.get('thinking', '')}"))
                    elif item_type == "tool_call":
                        blocks.append(
                            ContentBlock(
                                type="tool_use",
                                text=item.get("text", ""),
                                tool_name=item.get("name") or item.get("toolName"),
                                tool_input=item.get("input") or item.get("arguments", {}),
                            ),
                        )
                    else:
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                elif isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
            return blocks if blocks else None

        if isinstance(content, dict):
            return content.get("text", "") or __import__("json").dumps(content)

        return str(content)

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
