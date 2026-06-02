"""Unit tests for the CodexSkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.codex import CodexSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> CodexSkill:
    return CodexSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def codex_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "codex_session.jsonl"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``CodexSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.codex/sessions/2025/03/10/session.jsonl")
        assert CodexSkill.can_handle(path) == 1.0

    def test_related_dir(self) -> None:
        path = Path("/home/user/.codex/config.json")
        assert CodexSkill.can_handle(path) == 0.3

    def test_no_match(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/test.jsonl")
        assert CodexSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: CodexSkill, codex_fixture: Path) -> None:
        results = list(skill.extract_transcripts(codex_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count >= 5

    def test_user_and_assistant_roles(self, skill: CodexSkill, codex_fixture: Path) -> None:
        results = list(skill.extract_transcripts(codex_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_session_metadata_extracted(self, skill: CodexSkill, codex_fixture: Path) -> None:
        results = list(skill.extract_transcripts(codex_fixture))
        result = results[0]
        assert result.model == "o4-mini"
        assert result.session_id == "codex-sess-xyz789"

    def test_command_becomes_user_message(self, skill: CodexSkill, codex_fixture: Path) -> None:
        results = list(skill.extract_transcripts(codex_fixture))
        result = results[0]
        # Command records should appear as user messages
        contents = [m.content for m in result.messages]
        command_contents = [c for c in contents if isinstance(c, str) and "find ." in c]
        assert len(command_contents) >= 1

    def test_timestamps_present(self, skill: CodexSkill, codex_fixture: Path) -> None:
        results = list(skill.extract_transcripts(codex_fixture))
        result = results[0]
        assert result.started_at is not None
        assert "2025-03-10" in result.started_at

    def test_session_meta_skipped_as_message(
        self, skill: CodexSkill, codex_fixture: Path
    ) -> None:
        """session_meta records should not appear as messages."""
        results = list(skill.extract_transcripts(codex_fixture))
        result = results[0]
        for m in result.messages:
            assert "session_meta" not in str(m.metadata)

    def test_project_name_from_path(self, skill: CodexSkill) -> None:
        path = Path("/home/user/.codex/sessions/2025/03/10/my-session.jsonl")
        results = list(skill.extract_transcripts(path))
        assert results[0].project_name == "my-session"


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_skips_bad_json_lines(self, skill: CodexSkill, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text(
            json.dumps({"type": "input", "role": "user", "content": "good"}) + "\n"
            "this is not json\n"
            + json.dumps({"type": "response_item", "content": "also good"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 2
        assert len(results[0].warnings) >= 1

    def test_empty_file(self, skill: CodexSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: CodexSkill, codex_fixture: Path) -> None:
        issues = skill.validate_source(codex_fixture)
        assert issues == []

    def test_missing_file(self, skill: CodexSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.jsonl")
        assert len(issues) == 1

    def test_wrong_extension(self, skill: CodexSkill, tmp_path: Path) -> None:
        f = tmp_path / "wrong.md"
        f.write_text("not json", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1

    def test_empty_file(self, skill: CodexSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = CodexSkill.metadata()
        assert meta.name == "codex"
        assert meta.display_name == "OpenAI Codex CLI"
        assert meta.priority == 10
