"""Unit tests for the SkillRegistry.

Covers registration, discovery, conflict resolution, lookup, and extraction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.base import SkillMetadata, TranscriptSkill
from backend.skills.providers import (
    AiderSkill,
    ClaudeCodeSkill,
    CodexSkill,
    GenericSkill,
    KimiSkill,
    VibeSkill,
)
from backend.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_registry() -> SkillRegistry:
    """Return an empty :class:`SkillRegistry`."""
    return SkillRegistry()


@pytest.fixture
def full_registry(empty_registry: SkillRegistry) -> SkillRegistry:
    """Return a registry with all built-in skills discovered."""
    empty_registry.discover_builtin_skills()
    return empty_registry


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for skill registration and unregistration."""

    def test_register_single(self, empty_registry: SkillRegistry) -> None:
        """Registering a single skill increases the count."""
        empty_registry.register(ClaudeCodeSkill)
        assert len(empty_registry) == 1
        assert ClaudeCodeSkill in empty_registry

    def test_register_duplicate_is_noop(self, empty_registry: SkillRegistry) -> None:
        """Registering the same skill twice is a no-op."""
        empty_registry.register(ClaudeCodeSkill)
        empty_registry.register(ClaudeCodeSkill)
        assert len(empty_registry) == 1

    def test_unregister(self, empty_registry: SkillRegistry) -> None:
        """Unregistering a skill removes it."""
        empty_registry.register(ClaudeCodeSkill)
        empty_registry.unregister(ClaudeCodeSkill)
        assert len(empty_registry) == 0
        assert ClaudeCodeSkill not in empty_registry

    def test_register_invalid_type_raises(self, empty_registry: SkillRegistry) -> None:
        """Registering a non-skill class raises :class:`TypeError`."""
        with pytest.raises(TypeError):
            empty_registry.register(str)  # type: ignore[arg-type]

    def test_list_skills(self, full_registry: SkillRegistry) -> None:
        ""``list_skills`` returns metadata for every registered skill."""
        metas = full_registry.list_skills()
        names = {m.name for m in metas}
        assert "claude_code" in names
        assert "codex" in names
        assert "kimi" in names
        assert "vibe" in names
        assert "agy" in names
        assert "aider" in names
        assert "generic" in names
        assert len(metas) == 7

    def test_get_skill_by_name(self, full_registry: SkillRegistry) -> None:
        """Looking up by name returns the correct skill class."""
        found = full_registry.get_skill_by_name("claude_code")
        assert found is ClaudeCodeSkill

    def test_get_skill_by_name_not_found(self, full_registry: SkillRegistry) -> None:
        """Looking up an unknown name returns ``None``."""
        assert full_registry.get_skill_by_name("nonexistent") is None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    """Tests for the built-in skill discovery mechanism."""

    def test_discover_registers_all_seven(self, empty_registry: SkillRegistry) -> None:
        """``discover_builtin_skills`` registers exactly 7 skills."""
        empty_registry.discover_builtin_skills()
        assert len(empty_registry) == 7

    def test_discover_is_idempotent(self, empty_registry: SkillRegistry) -> None:
        """Calling ``discover_builtin_skills`` twice does not duplicate."""
        empty_registry.discover_builtin_skills()
        empty_registry.discover_builtin_skills()
        assert len(empty_registry) == 7


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    """Tests for the ``get_skill_for_path`` scoring and tie-breaking rules."""

    def test_claude_exact_match_wins(self, full_registry: SkillRegistry) -> None:
        """A path inside ``.claude/projects/`` should select ClaudeCodeSkill."""
        path = Path("/home/user/.claude/projects/myapp/2025-01-15.jsonl")
        winner = full_registry.get_skill_for_path(path)
        assert winner is ClaudeCodeSkill

    def test_codex_exact_match_wins(self, full_registry: SkillRegistry) -> None:
        """A path inside ``.codex/sessions/`` should select CodexSkill."""
        path = Path("/home/user/.codex/sessions/2025/03/10/abc123.jsonl")
        winner = full_registry.get_skill_for_path(path)
        assert winner is CodexSkill

    def test_kimi_exact_match_wins(self, full_registry: SkillRegistry) -> None:
        """A path inside ``.kimi/sessions/`` should select KimiSkill."""
        path = Path("/home/user/.kimi/sessions/default/sess-001/wire.jsonl")
        winner = full_registry.get_skill_for_path(path)
        assert winner is KimiSkill

    def test_vibe_exact_match_wins(self, full_registry: SkillRegistry) -> None:
        """A path inside ``.vibe/logs/session/`` should select VibeSkill."""
        path = Path("/home/user/.vibe/logs/session/session_2025-02-20.json")
        winner = full_registry.get_skill_for_path(path)
        assert winner is VibeSkill

    def test_aider_exact_match_wins(self, full_registry: SkillRegistry) -> None:
        """A filename ``.aider.chat.history.md`` should select AiderSkill."""
        path = Path("/home/user/project/.aider.chat.history.md")
        winner = full_registry.get_skill_for_path(path)
        assert winner is AiderSkill

    def test_claude_generic_dir(self, full_registry: SkillRegistry) -> None:
        """A path inside ``.claude/`` (but not projects) scores 0.3."""
        path = Path("/home/user/.claude/config.json")
        winner = full_registry.get_skill_for_path(path)
        # GenericSkill scores 0.1, ClaudeCodeSkill scores 0.3
        assert winner is ClaudeCodeSkill

    def test_generic_fallback_for_unknown(self, full_registry: SkillRegistry) -> None:
        """An unknown ``.jsonl`` file falls back to GenericSkill."""
        path = Path("/tmp/random_file.jsonl")
        winner = full_registry.get_skill_for_path(path)
        assert winner is GenericSkill

    def test_generic_fallback_for_txt(self, full_registry: SkillRegistry) -> None:
        """A ``.txt`` file falls back to GenericSkill."""
        path = Path("/tmp/notes.txt")
        winner = full_registry.get_skill_for_path(path)
        assert winner is GenericSkill

    def test_no_skill_for_unsupported(self, full_registry: SkillRegistry) -> None:
        """A file with no matching extension returns ``None``."""
        path = Path("/tmp/image.png")
        winner = full_registry.get_skill_for_path(path)
        assert winner is None

    def test_priority_tiebreak(self, empty_registry: SkillRegistry) -> None:
        """When two skills have the same can_handle score, lower priority wins."""

        class HighPrioritySkill(TranscriptSkill):
            @classmethod
            def metadata(cls) -> SkillMetadata:
                return SkillMetadata(
                    name="high_p", version="1", display_name="High",
                    description="x", supported_formats=[".txt"], priority=5,
                )

            @classmethod
            def can_handle(cls, path: Path) -> float:
                return 0.5

            def extract_transcripts(self, path, **options):
                return iter([])

            def validate_source(self, path):
                return []

        class LowPrioritySkill(TranscriptSkill):
            @classmethod
            def metadata(cls) -> SkillMetadata:
                return SkillMetadata(
                    name="low_p", version="1", display_name="Low",
                    description="x", supported_formats=[".txt"], priority=50,
                )

            @classmethod
            def can_handle(cls, path: Path) -> float:
                return 0.5

            def extract_transcripts(self, path, **options):
                return iter([])

            def validate_source(self, path):
                return []

        empty_registry.register(LowPrioritySkill)
        empty_registry.register(HighPrioritySkill)

        winner = empty_registry.get_skill_for_path(Path("/tmp/test.txt"))
        # Both score 0.5, but HighPrioritySkill has lower priority number (5 < 50)
        assert winner is HighPrioritySkill


# ---------------------------------------------------------------------------
# Extraction convenience
# ---------------------------------------------------------------------------


class TestExtractConvenience:
    """Tests for the ``extract`` convenience method."""

    def test_extract_returns_empty_when_no_skill(
        self, full_registry: SkillRegistry
    ) -> None:
        """``extract`` returns an empty list when no skill matches."""
        results = full_registry.extract(Path("/tmp/image.gif"))
        assert results == []


# ---------------------------------------------------------------------------
# Representation
# ---------------------------------------------------------------------------


class TestRepresentation:
    """Tests for ``__repr__`` and similar dunder methods."""

    def test_repr(self, full_registry: SkillRegistry) -> None:
        """The repr contains the names of all registered skills."""
        r = repr(full_registry)
        assert "SkillRegistry" in r
        assert "claude_code" in r
        assert "generic" in r
