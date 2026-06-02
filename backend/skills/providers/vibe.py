"""Skill for extracting transcripts from Vibe session JSON files.

Handles the ``~/.vibe/logs/session/session_*.json`` format where each
file is a JSON document containing a Vibe conversation session.
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
    detect_project_name_from_path,
    parse_iso_timestamp,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------


class VibeSkill(TranscriptSkill):
    """Extract transcripts from Vibe ``session_*.json`` conversation logs.

    Directory layout::

        ~/.vibe/logs/session/
            session_<timestamp>.json

    The JSON document is expected to have a top-level structure such as::

        {
            "session_id": "...",
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ],
            "created_at": "2024-01-01T00:00:00Z"
        }
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="vibe",
            version="1.0.0",
            display_name="Vibe",
            description="Parse Vibe JSON session logs from "
                        "~/.vibe/logs/session/session_*.json",
            supported_formats=[".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://github.com/vibe-cli/vibe",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``.vibe/logs/session/``
        * ``0.3`` — path contains ``.vibe/`` but not the logs/session sub-dir.
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if ".vibe" not in parts:
            return 0.0
        idx = parts.index(".vibe")
        if (
            idx + 3 < len(parts)
            and parts[idx + 1] == "logs"
            and parts[idx + 2] == "session"
        ):
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
        """Yield :class:`ExtractedTranscript` from a Vibe session JSON file."""
        path = path.resolve()
        result = ExtractedTranscript(
            source_type="vibe",
            source_path=path,
            skill_name="vibe",
            project_name=detect_project_name_from_path(path),
        )

        if not path.exists():
            result.errors.append(f"File not found: {path}")
            yield result
            return

        if path.is_dir():
            for json_file in sorted(path.glob("session_*.json")):
                yield from self.extract_transcripts(json_file, **options)
            if not list(path.glob("session_*.json")):
                for json_file in sorted(path.glob("*.json")):
                    yield from self.extract_transcripts(json_file, **options)
            return

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            result.errors.append(f"JSON parse error: {exc}")
            yield result
            return
        except OSError as exc:
            result.errors.append(f"Cannot read file: {exc}")
            yield result
            return

        if not isinstance(data, dict):
            result.errors.append(f"Expected JSON object, got {type(data).__name__}")
            yield result
            return

        result.session_id = data.get("session_id") or data.get("id")
        result.model = data.get("model") or data.get("model_name")
        result.started_at = parse_iso_timestamp(
            data.get("created_at") or data.get("started_at") or data.get("timestamp")
        )
        result.ended_at = parse_iso_timestamp(
            data.get("ended_at") or data.get("finished_at")
        )
        result.metadata = {k: v for k, v in data.items() if k not in {
            "session_id", "id", "model", "model_name", "created_at",
            "started_at", "ended_at", "finished_at", "timestamp",
            "messages", "conversation", "history", "turns",
        }}

        messages = self._extract_messages(data)
        if messages is None:
            result.errors.append("No 'messages' or 'conversation' array found in JSON")
            yield result
            return

        for idx, msg in enumerate(messages):
            result.raw_lines += 1
            norm_msg = self._normalize_message(msg, idx)
            if norm_msg is not None:
                result.messages.append(norm_msg)
                result.parsed_lines += 1
            else:
                result.warnings.append(
                    f"Could not normalise message at index {result.raw_lines}"
                )

        if result.messages:
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
            json_files = list(path.glob("*.json"))
            if not json_files:
                issues.append(f"No .json files found in: {path}")
            return issues

        if path.suffix != ".json":
            issues.append(f"Expected .json, got {path.suffix}")

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            issues.append(f"Cannot parse JSON: {exc}")
            return issues

        if not isinstance(data, dict):
            issues.append(f"Root is not a JSON object (got {type(data).__name__})")
        elif "messages" not in data and "conversation" not in data and "history" not in data:
            issues.append(
                "No 'messages', 'conversation', or 'history' key found — "
                "may not be a Vibe session file"
            )

        return issues

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_messages(self, data: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Extract the messages array from the Vibe JSON document."""
        for key in ("messages", "conversation", "history", "turns", "chats"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        return None

    def _normalize_message(
        self,
        msg: dict[str, Any],
        index: int,
    ) -> NormalizedMessage | None:
        """Convert a raw Vibe message dict into a :class:`NormalizedMessage`."""
        if not isinstance(msg, dict):
            return None

        speaker = msg.get("role", "")
        if isinstance(speaker, str):
            speaker = speaker.lower()
            if speaker in ("human", "user"):
                speaker = "user"
            elif speaker in ("ai", "assistant", "bot"):
                speaker = "assistant"
            elif speaker not in ("user", "assistant", "system", "tool"):
                speaker = "assistant"
        else:
            speaker = "assistant"

        content = msg.get("content")
        timestamp = parse_iso_timestamp(
            msg.get("timestamp") or msg.get("created_at") or msg.get("time")
        )
        model = msg.get("model") or msg.get("model_name")
        msg_type = msg.get("type", "message")

        normalised_content = self._normalise_content(content)

        if normalised_content is None:
            return None

        return NormalizedMessage(
            speaker=speaker,
            content=normalised_content,
            sequence=index,
            timestamp=timestamp,
            message_type=msg_type if isinstance(msg_type, str) else "message",
            model=model,
            metadata={k: v for k, v in msg.items() if k not in {
                "role", "content", "timestamp", "created_at", "model",
                "model_name", "type", "time",
            }},
        )

    def _normalise_content(
        self,
        content: Any,
    ) -> str | list[ContentBlock] | None:
        """Convert raw content to a normalised form."""
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
                        blocks.append(ContentBlock(type="tool_result", text=result_text))
                    elif item_type == "image":
                        blocks.append(
                            ContentBlock(
                                type="image",
                                text=item.get("text", ""),
                                mime_type=item.get("mime_type") or item.get("media_type"),
                            ),
                        )
                    else:
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                elif isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
            return blocks if blocks else None

        if isinstance(content, dict):
            return content.get("text", "") or json.dumps(content)

        if content is not None:
            return str(content)

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
