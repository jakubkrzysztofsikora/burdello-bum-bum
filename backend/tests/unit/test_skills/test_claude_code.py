"""Unit tests for the ClaudeCodeSkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.claude_code import ClaudeCodeSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> ClaudeCodeSkill:
    return ClaudeCodeSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def claude_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "claude_session.jsonl"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``ClaudeCodeSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/session.jsonl")
        assert ClaudeCodeSkill.can_handle(path) == 1.0

    def test_related_dir(self) -> None:
        path = Path("/home/user/.claude/config.json")
        assert ClaudeCodeSkill.can_handle(path) == 0.3

    def test_no_match(self) -> None:
        path = Path("/home/user/.codex/sessions/2025/01/01/test.jsonl")
        assert ClaudeCodeSkill.can_handle(path) == 0.0

    def test_no_match_random_file(self) -> None:
        path = Path("/tmp/random.txt")
        assert ClaudeCodeSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_all_messages(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count >= 8  # at least 8 messages in fixture

    def test_message_roles(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_tool_use_message(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        tool_uses = [m for m in result.messages if m.message_type == "tool_use"]
        assert len(tool_uses) >= 2  # two tool_use blocks in fixture
        # Check first tool_use has proper block structure
        blocks = tool_uses[0].content
        assert isinstance(blocks, list)
        assert blocks[0].type == "tool_use"
        assert blocks[0].tool_name == "Read"

    def test_tool_result_message(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        tool_results = [m for m in result.messages if m.message_type == "tool_result"]
        assert len(tool_results) >= 2

    def test_thinking_message(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        thinking = [m for m in result.messages if m.message_type == "thinking"]
        assert len(thinking) == 1

    def test_summary_message(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        summaries = [m for m in result.messages if m.message_type == "summary"]
        assert len(summaries) == 1

    def test_session_id_extracted(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        assert result.session_id == "sess-abc123"

    def test_model_extracted(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        assert result.model == "claude-sonnet-4-20250514"

    def test_project_name_from_path(self, skill: ClaudeCodeSkill) -> None:
        path = Path("/home/user/.claude/projects/webapp/session.jsonl")
        results = list(skill.extract_transcripts(path))
        assert results[0].project_name == "webapp"

    def test_timestamps_present(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        results = list(skill.extract_transcripts(claude_fixture))
        result = results[0]
        assert result.started_at is not None
        assert result.ended_at is not None
        assert "2025-01-15" in result.started_at


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_skips_bad_json_lines(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text(
            json.dumps({"type": "message", "role": "human", "content": "good"}) + "\n"
            "this is not json\n"
            + json.dumps({"type": "message", "role": "assistant", "content": "also good"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert results[0].success
        assert results[0].message_count == 2
        assert len(results[0].warnings) == 1  # one bad line warning

    def test_missing_role_defaults_to_assistant(
        self, skill: ClaudeCodeSkill, tmp_path: Path
    ) -> None:
        f = tmp_path / "no_role.jsonl"
        f.write_text(
            json.dumps({"type": "message", "content": "no role here"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].messages[0].role == "assistant"

    def test_empty_file(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success

    def test_content_as_array(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "array_content.jsonl"
        f.write_text(
            json.dumps({
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello "},
                    {"type": "text", "text": "world!"},
                ],
            }) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert isinstance(results[0].messages[0].content, list)
        assert results[0].messages[0].content[0].type == "text"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: ClaudeCodeSkill, claude_fixture: Path) -> None:
        issues = skill.validate_source(claude_fixture)
        assert issues == []

    def test_missing_file(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.jsonl")
        assert len(issues) == 1
        assert "does not exist" in issues[0]

    def test_empty_directory(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path)
        assert len(issues) == 1
        assert "No .jsonl files found" in issues[0]

    def test_wrong_extension(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "wrong.md"
        f.write_text("not json", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1

    def test_non_dict_first_line(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "bad_first.jsonl"
        f.write_text('"just a string"\n', encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1

    def test_first_line_missing_fields(self, skill: ClaudeCodeSkill, tmp_path: Path) -> None:
        f = tmp_path / "missing_fields.jsonl"
        f.write_text(json.dumps({"foo": "bar"}) + "\n", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) == 1
        assert "lacks expected fields" in issues[0]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = ClaudeCodeSkill.metadata()
        assert meta.name == "claude_code"
        assert meta.version == "1.0.0"
        assert meta.priority == 10
        assert ".jsonl" in meta.supported_formats
