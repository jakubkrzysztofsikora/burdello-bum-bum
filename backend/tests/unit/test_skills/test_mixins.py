"""Unit tests for the shared skill mixins and utility functions.

Covers :class:`JSONLSkillMixin`, :class:`MarkdownSkillMixin`,
``parse_iso_timestamp``, and ``detect_project_name_from_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.base import NormalizedMessage
from backend.skills.mixins import (
    JSONLSkillMixin,
    MarkdownSkillMixin,
    detect_project_name_from_path,
    parse_iso_timestamp,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseIsoTimestamp:
    """Tests for ``parse_iso_timestamp``."""

    def test_none_returns_none(self) -> None:
        assert parse_iso_timestamp(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_iso_timestamp("") is None
        assert parse_iso_timestamp("   ") is None

    def test_integer_epoch(self) -> None:
        result = parse_iso_timestamp(1737632400)
        assert result is not None
        assert "2025" in result

    def test_float_epoch(self) -> None:
        result = parse_iso_timestamp(1737632400.0)
        assert result is not None
        assert "2025" in result

    def test_iso_string(self) -> None:
        result = parse_iso_timestamp("2025-01-15T09:23:17Z")
        assert result == "2025-01-15T09:23:17+00:00"

    def test_iso_string_with_offset(self) -> None:
        result = parse_iso_timestamp("2025-01-15T09:23:17+05:00")
        assert result is not None
        assert "+00:00" in result or "04:23:17" in result

    def test_invalid_string_returns_none(self) -> None:
        assert parse_iso_timestamp("not-a-date") is None

    def test_naive_datetime_gets_utc(self) -> None:
        result = parse_iso_timestamp("2025-01-15T09:23:17")
        assert result is not None
        assert "+00:00" in result


# ---------------------------------------------------------------------------
# Project name detection
# ---------------------------------------------------------------------------


class TestDetectProjectNameFromPath:
    """Tests for ``detect_project_name_from_path``."""

    def test_claude_projects(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/2025-01-15.jsonl")
        assert detect_project_name_from_path(path) == "myapp"

    def test_codex_sessions(self) -> None:
        path = Path("/home/user/.codex/sessions/2025/03/10/abc123.jsonl")
        assert detect_project_name_from_path(path) == "abc123"

    def test_kimi_sessions(self) -> None:
        path = Path("/home/user/.kimi/sessions/default/sess-001/wire.jsonl")
        assert detect_project_name_from_path(path) == "default"

    def test_vibe_logs(self) -> None:
        path = Path("/home/user/.vibe/logs/session/sess_001.json")
        assert detect_project_name_from_path(path) == "user"

    def test_antigravity_cli(self) -> None:
        path = Path("/home/user/.gemini/antigravity-cli/my-convo/messages.jsonl")
        assert detect_project_name_from_path(path) == "my-convo"

    def test_fallback_to_parent_dir(self) -> None:
        path = Path("/home/user/projects/website/index.html")
        assert detect_project_name_from_path(path) == "website"


# ---------------------------------------------------------------------------
# JSONL mixin
# ---------------------------------------------------------------------------


class _JSONLSkill(JSONLSkillMixin):
    """Concrete test subject for JSONLSkillMixin."""


class TestJSONLSkillMixin:
    """Tests for :class:`JSONLSkillMixin`."""

    @pytest.fixture
    def mixin(self) -> _JSONLSkill:
        return _JSONLSkill()

    @pytest.fixture
    def good_jsonl(self, tmp_path: Path) -> Path:
        f = tmp_path / "good.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n"
            + json.dumps({"role": "assistant", "content": "hi"}) + "\n",
            encoding="utf-8",
        )
        return f

    @pytest.fixture
    def bad_jsonl(self, tmp_path: Path) -> Path:
        f = tmp_path / "bad.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n"
            + "this is not json\n"
            + json.dumps({"role": "assistant", "content": "hi"}) + "\n",
            encoding="utf-8",
        )
        return f

    @pytest.fixture
    def blank_lines_jsonl(self, tmp_path: Path) -> Path:
        f = tmp_path / "blank.jsonl"
        f.write_text(
            "\n"
            + json.dumps({"role": "user", "content": "hello"}) + "\n"
            + "\n\n"
            + json.dumps({"role": "assistant", "content": "hi"}) + "\n"
            + "\n",
            encoding="utf-8",
        )
        return f

    @pytest.fixture
    def non_dict_jsonl(self, tmp_path: Path) -> Path:
        f = tmp_path / "non_dict.jsonl"
        f.write_text(
            '"just a string"\n'
            + json.dumps(["a", "list"]) + "\n"
            + json.dumps({"role": "user"}) + "\n",
            encoding="utf-8",
        )
        return f

    def test_read_jsonl_lines_good_file(
        self, mixin: _JSONLSkill, good_jsonl: Path
    ) -> None:
        lines = list(mixin.read_jsonl_lines(good_jsonl))
        assert len(lines) == 2
        assert lines[0]["role"] == "user"
        assert lines[1]["role"] == "assistant"

    def test_read_jsonl_lines_skips_bad_lines(
        self, mixin: _JSONLSkill, bad_jsonl: Path
    ) -> None:
        lines = list(mixin.read_jsonl_lines(bad_jsonl))
        assert len(lines) == 2  # bad line skipped

    def test_read_jsonl_lines_skips_blank_lines(
        self, mixin: _JSONLSkill, blank_lines_jsonl: Path
    ) -> None:
        lines = list(mixin.read_jsonl_lines(blank_lines_jsonl))
        assert len(lines) == 2

    def test_read_jsonl_lines_skips_non_dicts(
        self, mixin: _JSONLSkill, non_dict_jsonl: Path
    ) -> None:
        lines = list(mixin.read_jsonl_lines(non_dict_jsonl))
        assert len(lines) == 1  # only the dict survives

    def test_read_jsonl_lines_missing_file(
        self, mixin: _JSONLSkill, tmp_path: Path
    ) -> None:
        lines = list(mixin.read_jsonl_lines(tmp_path / "nope.jsonl"))
        assert lines == []

    def test_read_jsonl_with_recovery_good_file(
        self, mixin: _JSONLSkill, good_jsonl: Path
    ) -> None:
        objs, warnings = mixin.read_jsonl_with_recovery(good_jsonl)
        assert len(objs) == 2
        assert warnings == []

    def test_read_jsonl_with_recovery_bad_lines(
        self, mixin: _JSONLSkill, bad_jsonl: Path
    ) -> None:
        objs, warnings = mixin.read_jsonl_with_recovery(bad_jsonl)
        assert len(objs) == 2
        assert len(warnings) == 1
        assert "JSON parse error" in warnings[0]

    def test_read_jsonl_with_recovery_blank_lines(
        self, mixin: _JSONLSkill, blank_lines_jsonl: Path
    ) -> None:
        objs, warnings = mixin.read_jsonl_with_recovery(blank_lines_jsonl)
        assert len(objs) == 2
        assert warnings == []


# ---------------------------------------------------------------------------
# Markdown mixin
# ---------------------------------------------------------------------------


class _MarkdownSkill(MarkdownSkillMixin):
    """Concrete test subject for MarkdownSkillMixin."""


class TestMarkdownSkillMixin:
    """Tests for :class:`MarkdownSkillMixin`."""

    @pytest.fixture
    def mixin(self) -> _MarkdownSkill:
        return _MarkdownSkill()

    def test_detect_role_from_line_heading_human(self, mixin: _MarkdownSkill) -> None:
        assert mixin.detect_role_from_line("### Human") == "user"
        assert mixin.detect_role_from_line("## Human:") == "user"

    def test_detect_role_from_line_heading_assistant(
        self, mixin: _MarkdownSkill
    ) -> None:
        assert mixin.detect_role_from_line("### Assistant") == "assistant"
        assert mixin.detect_role_from_line("#### Assistant:") == "assistant"

    def test_detect_role_from_line_colon_prefix(self, mixin: _MarkdownSkill) -> None:
        assert mixin.detect_role_from_line("Human: hello") == "user"
        assert mixin.detect_role_from_line("Assistant: hi there") == "assistant"
        assert mixin.detect_role_from_line("User: question") == "user"
        assert mixin.detect_role_from_line("AI: answer") == "assistant"
        assert mixin.detect_role_from_line("System: config") == "system"

    def test_detect_role_from_line_no_match(self, mixin: _MarkdownSkill) -> None:
        assert mixin.detect_role_from_line("Just some text") is None
        assert mixin.detect_role_from_line("") is None

    def test_strip_role_marker(self, mixin: _MarkdownSkill) -> None:
        assert mixin.strip_role_marker("Human: hello") == "hello"
        assert mixin.strip_role_marker("Assistant: hi") == "hi"
        assert mixin.strip_role_marker("### Human\nsome text") == "some text"

    def test_parse_markdown_conversation_simple(self, mixin: _MarkdownSkill) -> None:
        text = "Human: Hello\n\nAssistant: Hi there!\n\nHuman: How are you?\n\nAssistant: I am fine."
        messages = mixin.parse_markdown_conversation(text)
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"
        assert messages[2].role == "user"
        assert messages[3].role == "assistant"

    def test_parse_markdown_conversation_multiline(
        self, mixin: _MarkdownSkill
    ) -> None:
        text = (
            "Human: Line one\n"
            "Line two\n"
            "Line three\n"
            "\n"
            "Assistant: Response one\n"
            "Response two"
        )
        messages = mixin.parse_markdown_conversation(text)
        assert len(messages) == 2
        assert "Line one\nLine two\nLine three" in messages[0].content
        assert "Response one\nResponse two" in messages[1].content

    def test_parse_markdown_conversation_with_headings(
        self, mixin: _MarkdownSkill
    ) -> None:
        text = "### Human\nQuestion?\n\n### Assistant\nAnswer!"
        messages = mixin.parse_markdown_conversation(text)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_parse_markdown_conversation_leading_junk_skipped(
        self, mixin: _MarkdownSkill
    ) -> None:
        text = "Some intro text\nMore intro\nHuman: Actual question\nAssistant: Actual answer"
        messages = mixin.parse_markdown_conversation(text)
        # Leading non-role lines before the first role are skipped
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Actual question\nMore intro"

    def test_extract_code_blocks(self, mixin: _MarkdownSkill) -> None:
        text = (
            "Here's some code:\n\n"
            "```python\n"
            "def hello():\n    return 'world'\n"
            "```\n\n"
            "And more text."
        )
        blocks = mixin.extract_code_blocks(text)
        assert len(blocks) == 3
        assert blocks[0].type == "text"
        assert blocks[1].type == "code"
        assert blocks[1].language == "python"
        assert "def hello():" in blocks[1].text
        assert blocks[2].type == "text"

    def test_extract_code_blocks_no_code(self, mixin: _MarkdownSkill) -> None:
        text = "Just plain text without any code blocks."
        blocks = mixin.extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0].type == "text"
        assert blocks[0].text == text
