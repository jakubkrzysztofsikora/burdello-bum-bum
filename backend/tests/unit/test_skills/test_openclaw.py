"""Unit tests for the OpenclawSkill."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.providers.openclaw import OpenclawSkill


@pytest.fixture
def skill() -> OpenclawSkill:
    return OpenclawSkill()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def openclaw_fixture(fixture_dir: Path) -> Path:
    return fixture_dir / "openclaw_session.jsonl"


class TestCanHandle:
    """Tests for ``OpenclawSkill.can_handle``."""

    def test_exact_match(self) -> None:
        path = Path("/home/user/.openclaw-autoclaw/agents/main/sessions/467c7305.jsonl")
        assert OpenclawSkill.can_handle(path) == 1.0

    def test_related_dir(self) -> None:
        path = Path("/home/user/.openclaw-autoclaw/config.json")
        assert OpenclawSkill.can_handle(path) == 0.3

    def test_no_match(self) -> None:
        path = Path("/home/user/.claude/projects/myapp/test.jsonl")
        assert OpenclawSkill.can_handle(path) == 0.0


class TestHappyPath:
    """Tests for successful transcript extraction."""

    def test_extracts_messages(self, skill: OpenclawSkill, openclaw_fixture: Path) -> None:
        results = list(skill.extract_transcripts(openclaw_fixture))
        assert len(results) == 1
        result = results[0]
        assert result.success
        assert result.message_count >= 2

    def test_user_and_assistant_roles(self, skill: OpenclawSkill, openclaw_fixture: Path) -> None:
        results = list(skill.extract_transcripts(openclaw_fixture))
        result = results[0]
        roles = [m.role for m in result.messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_cwd_in_metadata(self, skill: OpenclawSkill, openclaw_fixture: Path) -> None:
        results = list(skill.extract_transcripts(openclaw_fixture))
        result = results[0]
        assert result.metadata.get("cwd") == "/Users/jakubsikora/Repos/personal/burdello-bum-bum"

    def test_timestamps_present(self, skill: OpenclawSkill, openclaw_fixture: Path) -> None:
        results = list(skill.extract_transcripts(openclaw_fixture))
        result = results[0]
        assert result.started_at is not None
        assert "2026-06-28" in result.started_at
