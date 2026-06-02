"""Unit tests for the AiderSkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.providers.aider import AiderSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> AiderSkill:
    return AiderSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def aider_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "aider_history.md"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``AiderSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/project/.aider.chat.history.md")
        assert AiderSkill.can_handle(path) == 1.0

    def test_partial_match(self) -> None:
        path = Path("/home/user/project/aider.chat.history.md")
        assert AiderSkill.can_handle(path) == 0.5

    def test_no_match(self) -> None:
        path = Path("/home/user/project/README.md")
        assert AiderSkill.can_handle(path) == 0.0

    def test_no_match_jsonl(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/session.jsonl")
        assert AiderSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        # The fixture has at least 6 Human/Assistant exchanges
        assert result.message_count >= 6

    def test_user_and_assistant_roles(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_alternating_roles(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        result = results[0]
        for i, msg in enumerate(result.messages):
            if i % 2 == 0:
                assert msg.role == "user"
            else:
                assert msg.role == "assistant"

    def test_code_blocks_extracted(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        result = results[0]
        # Assistant messages should contain code blocks
        assistant_msgs = [m for m in result.messages if m.role == "assistant"]
        assert len(assistant_msgs) >= 2

    def test_multiline_content(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        result = results[0]
        # Messages should contain multi-line content
        for msg in result.messages:
            assert len(msg.content) > 0

    def test_raw_lines_count(self, skill: AiderSkill, aider_fixture: Path) -> None:
        results = list(skill.extract_transcripts(aider_fixture))
        result = results[0]
        assert result.raw_lines > 0
        assert result.parsed_lines > 0


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_empty_file(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / ".aider.chat.history.md"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success
        assert len(results[0].warnings) >= 1

    def test_no_role_markers(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / ".aider.chat.history.md"
        f.write_text(
            "This is just some text\nwithout any role markers at all.\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        # No role markers = no messages extracted
        assert results[0].message_count == 0

    def test_file_with_only_human(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / ".aider.chat.history.md"
        f.write_text(
            "Human: Only human messages\nNo assistant replies here.\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert results[0].message_count == 1
        assert results[0].messages[0].role == "user"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: AiderSkill, aider_fixture: Path) -> None:
        issues = skill.validate_source(aider_fixture)
        assert issues == []

    def test_missing_file(self, skill: AiderSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.md")
        assert len(issues) == 1
        assert "does not exist" in issues[0]

    def test_directory_not_file(self, skill: AiderSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path)
        assert len(issues) == 1
        assert "Expected a file" in issues[0]

    def test_empty_file(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) == 1
        assert "empty" in issues[0].lower()

    def test_no_human_marker(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / "no_human.md"
        f.write_text("Assistant: Just an assistant message\n", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1
        assert "Human" in issues[0] or "User" in issues[0]

    def test_no_assistant_marker(self, skill: AiderSkill, tmp_path: Path) -> None:
        f = tmp_path / "no_assistant.md"
        f.write_text("Human: Just a human message\n", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) >= 1
        assert "Assistant" in issues[0] or "AI" in issues[0]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = AiderSkill.metadata()
        assert meta.name == "aider"
        assert meta.display_name == "Aider"
        assert meta.priority == 10
