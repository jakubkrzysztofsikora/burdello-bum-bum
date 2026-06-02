"""Transcript extraction skill system for Burdello Bum-Bum.

Provides the abstract base class, data models, shared mixins, skill
registry, and all built-in provider skills.

Quick start::

    from backend.skills import SkillRegistry

    registry = SkillRegistry()
    registry.discover_builtin_skills()

    transcripts = registry.extract(Path("~/.claude/projects/myapp/2025-01-15.jsonl"))
"""

from __future__ import annotations

from backend.skills.base import (
    ContentBlock,
    ExtractedTranscript,
    NormalizedMessage,
    SkillMetadata,
    TranscriptSkill,
)
from backend.skills.mixins import (
    JSONLSkillMixin,
    MarkdownSkillMixin,
    detect_project_name_from_path,
    parse_iso_timestamp,
)
from backend.skills.registry import SkillRegistry

__all__ = [
    # Base
    "TranscriptSkill",
    "SkillMetadata",
    "NormalizedMessage",
    "ContentBlock",
    "ExtractedTranscript",
    # Mixins & utilities
    "JSONLSkillMixin",
    "MarkdownSkillMixin",
    "parse_iso_timestamp",
    "detect_project_name_from_path",
    # Registry
    "SkillRegistry",
]
