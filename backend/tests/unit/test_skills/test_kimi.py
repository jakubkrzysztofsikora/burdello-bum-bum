"""Unit tests for the KimiSkill.

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.kimi import KimiSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> KimiSkill:
    return KimiSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def kimi_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "kimi_wire.jsonl"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``KimiSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.kimi/sessions/default/sess-001/wire.jsonl")
        assert KimiSkill.can_handle(path) == 1.0

    def test_related_dir(self) -> None:
        path = Path("/home/user/.kimi/config.json")
        assert KimiSkill.can_handle(path) == 0.3

    def test_no_match(self) -> None:
        path = Path("/home/user/.codex/sessions/2025/01/01/test.jsonl")
        assert KimiSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count >= 5

    def test_user_and_assistant_roles(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_model_extracted(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        result = results[0]
        assert result.model == "kimi-k2-72b"

    def test_tool_call_message(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        result = results[0]
        tool_uses = [m for m in result.messages if m.message_type == "tool_use"]
        assert len(tool_uses) == 1
        blocks = tool_uses[0].content
        assert isinstance(blocks, list)
        assert blocks[0].type == "tool_use"
        assert blocks[0].tool_name == "web_search"

    def test_tool_result_message(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        result = results[0]
        tool_results = [m for m in result.messages if m.message_type == "tool_result"]
        assert len(tool_results) == 1
        blocks = tool_results[0].content
        assert isinstance(blocks, list)
        assert blocks[0].type == "tool_result"

    def test_timestamps_from_epoch(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        results = list(skill.extract_transcripts(kimi_fixture))
        result = results[0]
        assert result.started_at is not None
        assert result.ended_at is not None

    def test_project_name_from_path(self, skill: KimiSkill) -> None:
        path = Path("/home/user/.kimi/sessions/my-group/my-session/wire.jsonl")
        results = list(skill.extract_transcripts(path))
        assert results[0].project_name == "my-group"


# ---------------------------------------------------------------------------
# Malformed data
# ---------------------------------------------------------------------------


class TestMalformedData:
    """Tests for graceful handling of bad data."""

    def test_skips_bad_json_lines(self, skill: KimiSkill, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text(
            json.dumps({"event_type": "TextPart", "text": "hello"}) + "\n"
            "this is not json\n"
            + json.dumps({"event_type": "user_message", "role": "user", "content": "good"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count >= 1
        assert len(results[0].warnings) >= 1

    def test_empty_file(self, skill: KimiSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success

    def test_text_parts_buffered_together(self, skill: KimiSkill, tmp_path: Path) -> None:
        """Consecutive TextPart events should be merged into one message."""
        f = tmp_path / "buffered.jsonl"
        f.write_text(
            json.dumps({"event_type": "TextPart", "text": "Hello "}) + "\n"
            + json.dumps({"event_type": "TextPart", "text": "world!"}) + "\n"
            + json.dumps({"event_type": "StatusUpdate", "status": "ok"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        # The two TextParts should be merged
        contents = [m.content for m in results[0].messages if isinstance(m.content, str)]
        merged = " ".join(contents)
        assert "Hello" in merged
        assert "world" in merged


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_file(self, skill: KimiSkill, kimi_fixture: Path) -> None:
        issues = skill.validate_source(kimi_fixture)
        assert issues == []

    def test_missing_file(self, skill: KimiSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.jsonl")
        assert len(issues) == 1

    def test_empty_file(self, skill: KimiSkill, tmp_path: Path) -> None:
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
        meta = KimiSkill.metadata()
        assert meta.name == "kimi"
        assert meta.display_name == "Moonshot Kimi"
        assert meta.priority == 10
