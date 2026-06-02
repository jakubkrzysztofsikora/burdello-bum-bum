"""Shared utility mixins for transcript extraction skills.

Provides reusable building blocks for reading JSONL and Markdown files,
parsing timestamps, and inferring project names from directory layouts.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from backend.skills.base import ContentBlock, NormalizedMessage

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

# Regex that matches trailing ``+HH:MM`` or ``-HH:MM`` offset
_UTC_OFFSET_RE = re.compile(r"^[+-]\d{2}:\d{2}$")


def parse_iso_timestamp(ts: Any) -> Optional[str]:
    """Normalise a candidate timestamp to strict ISO-8601 UTC.

    Accepts:
        * ``int`` / ``float`` — treated as Unix epoch seconds.
        * ``str`` — parsed via ``datetime.fromisoformat`` with some
          leniency for common CLI tool formats (e.g. ``Z`` suffix).

    Returns:
        An ISO-8601 string ending with ``+00:00`` (UTC), or ``None`` if
        *ts* is unparseable or null-ish.
    """
    if ts is None:
        return None

    if isinstance(ts, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return dt.isoformat()
        except (OSError, OverflowError, ValueError):
            return None

    if isinstance(ts, str):
        ts_str = ts.strip()
        if not ts_str:
            return None
        # Replace trailing "Z" with "+00:00" for fromisoformat compat
        if ts_str.upper().endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None

    return None


# ---------------------------------------------------------------------------
# Project-name heuristic
# ---------------------------------------------------------------------------


def detect_project_name_from_path(path: Path) -> Optional[str]:
    """Infer a project name from the directory layout.

    Heuristics (checked in order):

    1. If the path contains a ``.claude/projects/<name>/`` segment,
       return *name*.
    2. If the path contains a ``.codex/sessions/`` segment, look at the
       great-grandparent directory name (``YYYY/MM/DD/<session_file>.jsonl``
       → the session file stem is the project).
    3. If the path contains a ``.kimi/sessions/<group>/<session>/``
       segment, return *group*.
    4. If the path contains a ``.vibe/logs/session/`` segment, use the
       parent directory of ``session/`` (usually ``logs`` → not useful,
       so fall back to the ``.vibe`` parent directory name).
    5. If the path contains ``antigravity-cli/``, use the directory
       immediately after that segment.
    6. Otherwise return the name of the directory that contains the file.

    Args:
        path: Absolute or relative :class:`~pathlib.Path` to the source.

    Returns:
        A best-effort project name, or ``None`` if no heuristic matched.
    """
    path = path.resolve()
    parts = list(path.parts)

    # --- Claude Code ---
    try:
        idx = parts.index(".claude")
        if idx + 2 < len(parts) and parts[idx + 1] == "projects":
            return parts[idx + 2]
    except ValueError:
        pass

    # --- Codex ---
    try:
        idx = parts.index(".codex")
        if idx + 2 < len(parts) and parts[idx + 1] == "sessions":
            # File stem is the session / project identifier
            return path.stem
    except ValueError:
        pass

    # --- Kimi ---
    try:
        idx = parts.index(".kimi")
        if idx + 2 < len(parts) and parts[idx + 1] == "sessions":
            if idx + 3 < len(parts):
                return parts[idx + 2]  # the group folder
            return parts[idx + 2]
    except ValueError:
        pass

    # --- Vibe ---
    try:
        idx = parts.index(".vibe")
        if idx + 2 < len(parts) and parts[idx + 1] == "logs":
            # Use the parent dir name of .vibe
            if idx > 0:
                return parts[idx - 1]
    except ValueError:
        pass

    # --- Gemini / antigravity-cli ---
    try:
        idx = parts.index("antigravity-cli")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass

    # Fallback: parent directory name
    return path.parent.name if path.parent != path else None


# ---------------------------------------------------------------------------
# JSONL mixin
# ---------------------------------------------------------------------------


class JSONLSkillMixin(ABC):
    """Mixin for skills that consume newline-delimited JSON (JSONL).

    Provides line-by-line iteration with **error recovery**: malformed
    lines are logged as warnings and skipped rather than crashing the
    entire extraction.
    """

    def read_jsonl_lines(
        self,
        path: Path,
        encoding: str = "utf-8",
    ) -> Iterator[dict[str, Any]]:
        """Yield valid JSON objects from a JSONL file.

        Lines that fail to parse are logged and skipped.

        Args:
            path: Path to the ``.jsonl`` file.
            encoding: Text encoding.  Default ``"utf-8"``.

        Yields:
            Dicts representing individual JSON objects.
        """
        if not path.exists():
            logger.warning("JSONL file not found: %s", path)
            return

        line_number = 0
        try:
            with path.open("r", encoding=encoding) as fh:
                for raw_line in fh:
                    line_number += 1
                    line = raw_line.strip()
                    if not line:
                        continue  # skip blank lines
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            yield obj
                        else:
                            logger.warning(
                                "%s:%d — JSON line is not a dict (%s), skipping",
                                path,
                                line_number,
                                type(obj).__name__,
                            )
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "%s:%d — JSON parse error: %s. Line: %.200s",
                            path,
                            line_number,
                            exc,
                            line,
                        )
        except OSError as exc:
            logger.error("Cannot read %s: %s", path, exc)

    def read_jsonl_with_recovery(
        self,
        path: Path,
        encoding: str = "utf-8",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Read an entire JSONL file, returning objects + warnings.

        Args:
            path: Path to the ``.jsonl`` file.
            encoding: Text encoding.

        Returns:
            A tuple of ``(objects, warnings)`` where *warnings* contains
            human-readable descriptions of every skipped / malformed line.
        """
        objects: list[dict[str, Any]] = []
        warnings: list[str] = []

        if not path.exists():
            return objects, [f"File not found: {path}"]

        line_number = 0
        try:
            with path.open("r", encoding=encoding) as fh:
                for raw_line in fh:
                    line_number += 1
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            objects.append(obj)
                        else:
                            msg = (
                                f"{path}:{line_number} — JSON line is not a "
                                f"dict ({type(obj).__name__}), skipping"
                            )
                            warnings.append(msg)
                    except json.JSONDecodeError as exc:
                        msg = (
                            f"{path}:{line_number} — JSON parse error: {exc}. "
                            f"Line: {line[:200]}"
                        )
                        warnings.append(msg)
        except OSError as exc:
            warnings.append(f"Cannot read {path}: {exc}")

        return objects, warnings


# ---------------------------------------------------------------------------
# Markdown mixin
# ---------------------------------------------------------------------------


class MarkdownSkillMixin(ABC):
    """Mixin for skills that parse Markdown conversation files.

    Recognises common role markers such as ``Human:``, ``Assistant:``,
    ``User:``, ``AI:``, ``### Human``, ``## Assistant``, etc.
    """

    # Common role prefixes used by various CLI tools
    _ROLE_PATTERNS: list[tuple[re.Pattern, str]] = [
        # --- Headings ---
        (re.compile(r"^#{1,4}\s*Human\b", re.IGNORECASE), "user"),
        (re.compile(r"^#{1,4}\s*User\b", re.IGNORECASE), "user"),
        (re.compile(r"^#{1,4}\s*Assistant\b", re.IGNORECASE), "assistant"),
        (re.compile(r"^#{1,4}\s*AI\b", re.IGNORECASE), "assistant"),
        (re.compile(r"^#{1,4}\s*System\b", re.IGNORECASE), "system"),
        # --- Colon prefixes ---
        (re.compile(r"^Human\s*:\s*", re.IGNORECASE), "user"),
        (re.compile(r"^User\s*:\s*", re.IGNORECASE), "user"),
        (re.compile(r"^Assistant\s*:\s*", re.IGNORECASE), "assistant"),
        (re.compile(r"^AI\s*:\s*", re.IGNORECASE), "assistant"),
        (re.compile(r"^System\s*:\s*", re.IGNORECASE), "system"),
        # --- XML-style tags (Aider) ---
        (re.compile(r"^<\s*user\s*>", re.IGNORECASE), "user"),
        (re.compile(r"^</\s*user\s*>", re.IGNORECASE), "user"),
        (re.compile(r"^<\s*assistant\s*>", re.IGNORECASE), "assistant"),
        (re.compile(r"^</\s*assistant\s*>", re.IGNORECASE), "assistant"),
    ]

    def detect_role_from_line(self, line: str) -> Optional[str]:
        """Return the role slug (``"user"``, ``"assistant"``, ``"system"``)
        if *line* starts with a recognised role marker.

        Returns ``None`` when no pattern matches.
        """
        for pattern, role in self._ROLE_PATTERNS:
            if pattern.match(line):
                return role
        return None

    def strip_role_marker(self, line: str) -> str:
        """Remove the role prefix from *line* and return the remaining text.

        If no role marker is detected the line is returned unchanged.
        """
        for pattern, _role in self._ROLE_PATTERNS:
            match = pattern.match(line)
            if match:
                return line[match.end() :].strip()
        return line.strip()

    def parse_markdown_conversation(
        self,
        text: str,
        source_path: Optional[Path] = None,
    ) -> list[NormalizedMessage]:
        """Parse a Markdown document into a list of normalised messages.

        The parser state-machines through the text looking for role markers.
        Consecutive lines belonging to the same speaker are concatenated
        with newline separators.

        Args:
            text: Full Markdown document content.
            source_path: Optional path for error reporting.

        Returns:
            Ordered list of :class:`NormalizedMessage` objects.
        """
        messages: list[NormalizedMessage] = []
        current_role: Optional[str] = None
        current_lines: list[str] = []

        def _flush() -> None:
            nonlocal current_role, current_lines
            if current_role and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    messages.append(
                        NormalizedMessage(
                            speaker=current_role,
                            content=content,
                            metadata={"source": str(source_path)} if source_path else {},
                        ),
                    )
            current_role = None
            current_lines = []

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            detected = self.detect_role_from_line(line)

            if detected is not None:
                # New speaker — flush previous buffer
                _flush()
                current_role = detected
                remainder = self.strip_role_marker(line)
                if remainder:
                    current_lines.append(remainder)
            else:
                # Continuation of the current speaker
                if current_role is not None:
                    current_lines.append(line)
                # If we have not seen a role yet, skip leading non-role lines

        _flush()
        return messages

    def extract_code_blocks(
        self,
        text: str,
    ) -> list[ContentBlock]:
        """Extract fenced code blocks from Markdown text as ContentBlocks.

        Regular text is returned as ``type="text"`` blocks, while
        triple-backtick regions become ``type="code"`` blocks with
        the language tag populated when present.

        Args:
            text: Markdown content.

        Returns:
            Ordered list of :class:`ContentBlock` objects.
        """
        blocks: list[ContentBlock] = []
        pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
        last_end = 0

        for match in pattern.finditer(text):
            # Text before the code block
            if match.start() > last_end:
                text_part = text[last_end : match.start()].strip()
                if text_part:
                    blocks.append(ContentBlock(type="text", text=text_part))

            # The code block itself
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

        # If no code blocks found, return the whole text as a single block
        if not blocks:
            blocks.append(ContentBlock(type="text", text=text.strip()))

        return blocks
