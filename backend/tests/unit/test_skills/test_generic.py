"""Unit tests for the GenericSkill (fallback parser).

Tests happy-path extraction, malformed data handling, wrong file type
rejection, and ``can_handle`` scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.providers.generic import GenericSkill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> GenericSkill:
    return GenericSkill()


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ``GenericSkill.can_handle``."""

    def test_jsonl(self) -> None:
        path = Path("/tmp/random_file.jsonl")
        assert GenericSkill.can_handle(path) == 0.1

    def test_md(self) -> None:
        path = Path("/tmp/notes.md")
        assert GenericSkill.can_handle(path) == 0.1

    def test_txt(self) -> None:
        path = Path("/tmp/log.txt")
        assert GenericSkill.can_handle(path) == 0.1

    def test_no_match_png(self) -> None:
        path = Path("/tmp/image.png")
        assert GenericSkill.can_handle(path) == 0.0

    def test_no_match_no_extension(self) -> None:
        path = Path("/tmp/Makefile")
        assert GenericSkill.can_handle(path) == 0.0


# ---------------------------------------------------------------------------
# JSONL fallback
# ---------------------------------------------------------------------------


class TestJSONLFallback:
    """Tests for generic JSONL parsing."""

    def test_parses_simple_messages(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "generic.jsonl"
        f.write_text(
            json.dumps({"role": "user", "content": "Hello"}) + "\n"
            + json.dumps({"role": "assistant", "content": "Hi!"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert results[0].success
        assert results[0].message_count == 2

    def test_parses_without_role(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "no_role.jsonl"
        f.write_text(
            json.dumps({"content": "Hello"}) + "\n"
            + json.dumps({"content": "Hi!"}) + "\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        # Falls back to "assistant" role
        assert all(m.role == "assistant" for m in results[0].messages)

    def test_empty_jsonl(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Markdown fallback
# ---------------------------------------------------------------------------


class TestMarkdownFallback:
    """Tests for generic Markdown parsing."""

    def test_parses_role_markers(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "chat.md"
        f.write_text(
            "Human: Hello\n\nAssistant: Hi there!\n\nHuman: How are you?\n\nAssistant: Fine!\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert results[0].success
        assert results[0].message_count == 4

    def test_parses_heading_markers(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "chat.md"
        f.write_text(
            "### Human\nHello\n\n### Assistant\nHi there!\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 2

    def test_empty_md(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Plain text fallback
# ---------------------------------------------------------------------------


class TestTextFallback:
    """Tests for generic plain-text parsing."""

    def test_parses_prefix_markers(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "chat.txt"
        f.write_text(
            "USER: Hello\nASSISTANT: Hi there!\nUSER: How are you?\nASSISTANT: Fine!\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert results[0].success
        assert results[0].message_count == 4

    def test_parses_arrow_prefixes(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "chat.txt"
        f.write_text(
            ">> Hello\n<< Hi there!\n>> Question?\n<< Answer!\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 4

    def test_parses_qa_prefixes(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "chat.txt"
        f.write_text(
            "Q: What is Python?\nA: A programming language.\nQ: What is FastAPI?\nA: A web framework.\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 4

    def test_alternating_fallback(self, skill: GenericSkill, tmp_path: Path) -> None:
        """When no markers detected, falls back to alternating lines."""
        f = tmp_path / "chat.txt"
        f.write_text(
            "Hello\nHi there\nHow are you\nI'm fine\n",
            encoding="utf-8",
        )
        results = list(skill.extract_transcripts(f))
        assert results[0].success
        assert results[0].message_count == 4
        # Even lines are user, odd are assistant
        assert results[0].messages[0].role == "user"
        assert results[0].messages[1].role == "assistant"

    def test_empty_txt(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        results = list(skill.extract_transcripts(f))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Directory processing
# ---------------------------------------------------------------------------


class TestDirectoryProcessing:
    """Tests for processing directories."""

    def test_processes_mixed_files(self, skill: GenericSkill, tmp_path: Path) -> None:
        # Create a mix of files
        (tmp_path / "a.jsonl").write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text("Human: hi\nAssistant: hello\n", encoding="utf-8")
        (tmp_path / "c.txt").write_text("USER: test\nASSISTANT: reply\n", encoding="utf-8")
        results = list(skill.extract_transcripts(tmp_path))
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_empty_directory(self, skill: GenericSkill, tmp_path: Path) -> None:
        results = list(skill.extract_transcripts(tmp_path))
        assert len(results) == 1
        assert not results[0].success


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for ``validate_source``."""

    def test_valid_jsonl(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "valid.jsonl"
        f.write_text("{}", encoding="utf-8")
        issues = skill.validate_source(f)
        assert issues == []

    def test_valid_md(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "valid.md"
        f.write_text("Hello", encoding="utf-8")
        issues = skill.validate_source(f)
        assert issues == []

    def test_missing_file(self, skill: GenericSkill, tmp_path: Path) -> None:
        issues = skill.validate_source(tmp_path / "nope.jsonl")
        assert len(issues) == 1

    def test_empty_file(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        issues = skill.validate_source(f)
        assert len(issues) == 1
        assert "empty" in issues[0].lower()

    def test_unsupported_extension(self, skill: GenericSkill, tmp_path: Path) -> None:
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        issues = skill.validate_source(f)
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for the skill metadata descriptor."""

    def test_metadata(self) -> None:
        meta = GenericSkill.metadata()
        assert meta.name == "generic"
        assert meta.display_name == "Generic Fallback"
        assert meta.priority == 999  # Lowest priority
        assert ".jsonl" in meta.supported_formats
        assert ".md" in meta.supported_formats
        assert ".txt" in meta.supported_formats
