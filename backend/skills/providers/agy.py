"""Skill for extracting transcripts from Gemini Antigravity CLI sessions.

Handles the ``~/.gemini/antigravity-cli/`` directory layout which may
contain a mix of JSONL files and conversation sub-directories.
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


class AgySkill(TranscriptSkill, JSONLSkillMixin, MarkdownSkillMixin):
    """Extract transcripts from Gemini Antigravity CLI conversation logs.

    Directory layout::

        ~/.gemini/antigravity-cli/
            <conversation_dir>/
                messages.jsonl
                conversation.md
                metadata.json

    The format is a mix of JSONL message streams and optional Markdown
    conversation exports.
    """

    @classmethod
    def metadata(cls) -> SkillMetadata:
        return SkillMetadata(
            name="agy",
            version="1.0.0",
            display_name="Gemini Antigravity CLI",
            description="Parse Gemini Antigravity CLI conversation logs from "
                        "~/.gemini/antigravity-cli/ (mixed JSONL + Markdown)",
            supported_formats=[".jsonl", ".md", ".json"],
            priority=10,
            enabled=True,
            author="Burdello Bum-Bum",
            url="https://github.com/google-gemini/antigravity-cli",
        )

    @classmethod
    def can_handle(cls, path: Path) -> float:
        """Score how well this skill can parse *path*.

        * ``1.0`` — path contains ``antigravity-cli/``
        * ``0.0`` — no match.
        """
        parts = list(path.resolve().parts)
        if "antigravity-cli" in parts:
            return 1.0
        return 0.0

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_transcripts(
        self,
        path: Path,
        **options: Any,
    ) -> Iterator[ExtractedTranscript]:
        """Yield :class:`ExtractedTranscript` from Antigravity CLI logs."""
        path = path.resolve()

        if not path.exists():
            result = ExtractedTranscript(
                source_path=path,
                skill_name=self.metadata().name,
                messages=[],
            )
            result.errors.append(f"Path not found: {path}")
            yield result
            return

        if path.is_dir():
            # Process all conversation directories
            found_any = False
            for subdir in sorted(d for d in path.iterdir() if d.is_dir()):
                found_any = True
                yield from self._process_conversation_dir(subdir)
            # Also try JSONL files directly in the root
            for jsonl_file in sorted(path.glob("*.jsonl")):
                found_any = True
                yield from self._process_jsonl_file(jsonl_file)
            # And markdown files
            for md_file in sorted(path.glob("*.md")):
                found_any = True
                yield from self._process_markdown_file(md_file)

            if not found_any:
                result = ExtractedTranscript(
                    source_path=path,
                    skill_name=self.metadata().name,
                    messages=[],
                )
                result.warnings.append(f"No conversation files found in: {path}")
                yield result
            return

        # Single file
        if path.suffix == ".jsonl":
            yield from self._process_jsonl_file(path)
        elif path.suffix == ".md":
            yield from self._process_markdown_file(path)
        elif path.suffix == ".json":
            yield from self._process_json_file(path)
        else:
            result = ExtractedTranscript(
                source_path=path,
                skill_name=self.metadata().name,
                messages=[],
            )
            result.warnings.append(f"Unsupported file type: {path.suffix}")
            yield result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_source(self, path: Path) -> list[str]:
        """Return a list of issues with the source path."""
        issues: list[str] = []
        path = path.resolve()

        if not path.exists():
            return [f"Path does not exist: {path}"]

        if path.is_dir():
            has_files = bool(
                list(path.rglob("*.jsonl"))
                or list(path.rglob("*.md"))
                or list(path.rglob("*.json"))
            )
            if not has_files:
                issues.append(
                    f"No .jsonl, .md, or .json files found under: {path}"
                )
            return issues

        if path.suffix not in (".jsonl", ".md", ".json"):
            issues.append(f"Expected .jsonl, .md, or .json, got {path.suffix}")

        return issues

    # ------------------------------------------------------------------
    # Directory / file processors
    # ------------------------------------------------------------------

    def _process_conversation_dir(self, dir_path: Path) -> Iterator[ExtractedTranscript]:
        """Process a single conversation sub-directory."""
        # Prefer JSONL files
        jsonl_files = sorted(dir_path.glob("*.jsonl"))
        if jsonl_files:
            for jsonl_file in jsonl_files:
                yield from self._process_jsonl_file(jsonl_file)
            return

        # Fall back to Markdown
        md_files = sorted(dir_path.glob("*.md"))
        if md_files:
            for md_file in md_files:
                yield from self._process_markdown_file(md_file)
            return

        # Try JSON
        json_files = sorted(dir_path.glob("*.json"))
        for json_file in json_files:
            yield from self._process_json_file(json_file)

    def _process_jsonl_file(self, path: Path) -> Iterator[ExtractedTranscript]:
        """Process a single JSONL file."""
        result = ExtractedTranscript(
            source_path=path,
            skill_name=self.metadata().name,
            messages=[],
            project_name=detect_project_name_from_path(path),
        )

        current_model: str | None = None

        for record in self.read_jsonl_lines(path):
            result.raw_lines += 1

            role = self._extract_role(record)
            content = self._extract_content(record)
            timestamp = self._extract_timestamp(record)
            model = record.get("model") or record.get("model_name")
            if model:
                current_model = model

            if content is None:
                result.warnings.append(
                    f"Line {result.raw_lines}: could not extract content"
                )
                continue

            msg_type = record.get("type", "message")
            if not isinstance(msg_type, str):
                msg_type = "message"

            result.messages.append(
                NormalizedMessage(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    message_type=msg_type,
                    model=current_model,
                    metadata={k: v for k, v in record.items() if k not in {
                        "role", "content", "timestamp", "created_at",
                        "model", "model_name", "type",
                    }},
                ),
            )
            result.parsed_lines += 1

        result.model = current_model
        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    def _process_markdown_file(self, path: Path) -> Iterator[ExtractedTranscript]:
        """Process a single Markdown file."""
        result = ExtractedTranscript(
            source_path=path,
            skill_name=self.metadata().name,
            messages=[],
            project_name=detect_project_name_from_path(path),
        )

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(f"Cannot read file: {exc}")
            yield result
            return

        messages = self.parse_markdown_conversation(text, source_path=path)
        result.messages.extend(messages)
        result.raw_lines = len(text.splitlines())
        result.parsed_lines = len(messages)

        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    def _process_json_file(self, path: Path) -> Iterator[ExtractedTranscript]:
        """Process a single JSON file (array of messages or object with messages)."""
        result = ExtractedTranscript(
            source_path=path,
            skill_name=self.metadata().name,
            messages=[],
            project_name=detect_project_name_from_path(path),
        )

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            result.errors.append(f"Cannot parse JSON: {exc}")
            yield result
            return

        messages: list[dict[str, Any]] = []
        if isinstance(data, list):
            messages = data
        elif isinstance(data, dict):
            for key in ("messages", "conversation", "history"):
                val = data.get(key)
                if isinstance(val, list):
                    messages = val
                    break
        else:
            result.errors.append(f"Expected JSON array or object, got {type(data).__name__}")
            yield result
            return

        current_model = data.get("model") if isinstance(data, dict) else None

        for msg in messages:
            result.raw_lines += 1
            if not isinstance(msg, dict):
                result.warnings.append(f"Skipping non-dict message: {type(msg).__name__}")
                continue

            role = self._extract_role(msg)
            content = self._extract_content(msg)
            timestamp = self._extract_timestamp(msg)
            model = msg.get("model") or msg.get("model_name")
            if model:
                current_model = model

            if content is not None:
                result.messages.append(
                    NormalizedMessage(
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        model=current_model,
                    ),
                )
                result.parsed_lines += 1
            else:
                result.warnings.append(
                    f"Could not extract content from message at index {result.raw_lines}"
                )

        result.model = current_model
        if result.messages:
            result.started_at = result.messages[0].timestamp
            result.ended_at = result.messages[-1].timestamp

        yield result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_role(self, record: dict[str, Any]) -> str:
        """Map the role field to a normalised role slug."""
        raw_role = record.get("role", "")
        if isinstance(raw_role, str):
            role_lower = raw_role.lower()
            if role_lower in ("human", "user"):
                return "user"
            if role_lower in ("ai", "assistant", "bot", "model"):
                return "assistant"
            if role_lower == "system":
                return "system"
            if role_lower == "tool":
                return "tool"
        # Infer from sender/author
        sender = record.get("sender") or record.get("author")
        if isinstance(sender, str):
            sender_lower = sender.lower()
            if sender_lower in ("human", "user"):
                return "user"
            if sender_lower in ("ai", "assistant", "bot", "model", "gemini"):
                return "assistant"
        return "assistant"

    def _extract_timestamp(self, record: dict[str, Any]) -> str | None:
        """Pull a timestamp from a record."""
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
    ) -> str | list[ContentBlock] | None:
        """Convert raw content into a normalised form."""
        content = record.get("content")
        text = record.get("text")
        message = record.get("message")

        if content is None and text is not None:
            content = text
        if content is None and message is not None:
            content = message

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
                    elif item_type in ("tool_use", "tool_call", "function_call"):
                        blocks.append(
                            ContentBlock(
                                type="tool_use",
                                text=item.get("text", ""),
                                tool_name=item.get("name") or item.get("tool_name"),
                                tool_input=item.get("input") or item.get("arguments", {}),
                            ),
                        )
                    elif item_type in ("tool_result", "function_result"):
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
