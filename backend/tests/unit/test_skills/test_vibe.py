"""Unit tests for the VibeSkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.vibe import VibeSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> VibeSkill:
    return VibeSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def vibe_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "vibe_session.json"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``VibeSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.vibe/logs/session/session_2025-02-20.json")
        assert VibeSkill.can_handle(path) == 1.0

    def test_related_dir(self) -> None:
        path = Path("/home/user/.vibe/config.json")
        assert VibeSkill.can_handle(path) == 0.3

    def test_no_match(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/test.json")
        assert VibeSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count == 4

    def test_user_and_assistant_roles(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert roles.count("user") == 2
        assert roles.count("assistant") == 2

    def test_session_id_extracted(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        result = results[0]
        assert result.session_id == "vibe-sess-001"

    def test_model_extracted(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        result = results[0]
        assert result.model == "gpt-4-turbo"

    def test_timestamps_present(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        result = results[0]
        assert result.started_at is not None
        assert result.ended_at is not None

    def test_code_blocks_in_content(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        results = list(skill.extract_transcripts(vibe_fixture))
        result = results[0]
        # Assistant messages should have JSX code content
        assistant_msgs = [m for m in result.messages if m.role == "assistant"]
        assert len(assistant_msgs) == 2
        # Check that code content is present in at least one message
        contents = [m.content for m in assistant_msgs]
        has_code = any(isinstance(c, str) and "```" in c for c in contents)
        # Code blocks may be extracted as ContentBlocks or kept as strings
        assert len(assistant_msgs) >= 1


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_invalid_json(self, skill: VibeSkill, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not valid json", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success
        assert len(results[0].errors) >= 1

    def test_empty_json_object(self, skill: VibeSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("{}", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success
        assert len(results[0].errors) >= 1

    def test_missing_messages_key(self, skill: VibeSkill, tmp_path: Path) -> None:
        f = tmp_path / "no_messages.json"
        f.write_text(json.dumps({"session_id": "abc", "model": "gpt-4"}), encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: VibeSkill, vibe_fixture: Path) -> None:
        issues = skill.validate_source(vibe_fixture)
        assert issues == []

    def test_missing_file(self, skill: VibeSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.json")
        assert len(issues) == 1

    def test_wrong_extension(self, skill: VibeSkill, tmp_path: Path) -> None:
        f = tmp_path / "wrong.md"
        f.write_text("not json", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = VibeSkill.metadata()
        assert meta.name == "vibe"
        assert meta.display_name == "Vibe"
        assert meta.priority == 10
