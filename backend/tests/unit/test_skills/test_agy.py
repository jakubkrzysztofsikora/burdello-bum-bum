"""Unit tests for the AgySkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.agy import AgySkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> AgySkill:
    return AgySkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def agy_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "agy_conversation.jsonl"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``AgySkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.gemini/antigravity-cli/my-convo/messages.jsonl")
        assert AgySkill.can_handle(path) == 1.0

    def test_no_match(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/test.jsonl")
        assert AgySkill.can_handle(path) == 0.0

    def test_no_match_codex(self) -> None:
        path = Path("/home/user/.codex/sessions/2025/01/01/test.jsonl")
        assert AgySkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: AgySkill, agy_fixture: Path) -> None:
        results = list(skill.extract_transcripts(agy_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count >= 6

    def test_user_and_assistant_roles(self, skill: AgySkill, agy_fixture: Path) -> None:
        results = list(skill.extract_transcripts(agy_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_model_extracted(self, skill: AgySkill, agy_fixture: Path) -> None:
        results = list(skill.extract_transcripts(agy_fixture))
        result = results[0]
        assert result.model == "gemini-2.5-pro"

    def test_code_messages_extracted(self, skill: AgySkill, agy_fixture: Path) -> None:
        results = list(skill.extract_transcripts(agy_fixture))
        result = results[0]
        # There should be assistant messages with code content
        assistant_msgs = [m for m in result.messages if m.role == "assistant"]
        assert len(assistant_msgs) >= 3

    def test_timestamps_present(self, skill: AgySkill, agy_fixture: Path) -> None:
        results = list(skill.extract_transcripts(agy_fixture))
        result = results[0]
        assert result.started_at is not None
        assert result.ended_at is not None

    def test_project_name_from_path(self, skill: AgySkill) -> None:
        path = Path("/home/user/.gemini/antigravity-cli/my-convo/messages.jsonl")
        results = list(skill.extract_transcripts(path))
        assert results[0].project_name == "my-convo"


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_skips_bad_json_lines(self, skill: AgySkill, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n"
            "this is not json\n"
            + json.dumps({"role": "model", "content": "good"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 2
        assert len(results[0].warnings) >= 1

    def test_empty_file(self, skill: AgySkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success

    def test_directory_with_subdirs(self, skill: AgySkill, tmp_path: Path) -> None:
        """When given a directory, should process conversation subdirs."""
        convo_dir = tmp_path / "convo1"
        convo_dir.mkdir()
        (convo_dir / "messages.jsonl").write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(tmp_path))
        assert len(results) >= 1
        assert any(r.success for r in results)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: AgySkill, agy_fixture: Path) -> None:
        issues = skill.validate_source(agy_fixture)
        assert issues == []

    def test_missing_file(self, skill: AgySkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.jsonl")
        assert len(issues) == 1

    def test_empty_directory(self, skill: AgySkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path)
        assert len(issues) == 1
        assert "No" in issues[0] and "files found" in issues[0]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = AgySkill.metadata()
        assert meta.name == "agy"
        assert meta.display_name == "Gemini Antigravity CLI"
        assert meta.priority == 10
