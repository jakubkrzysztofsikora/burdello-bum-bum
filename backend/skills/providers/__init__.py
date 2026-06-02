"""Built-in transcript extraction skill providers.

Exports all seven provider skills so they can be imported in bulk::

    from backend.skills.providers import (
        ClaudeCodeSkill, CodexSkill, KimiSkill,
        VibeSkill, AgySkill, AiderSkill, GenericSkill,
    )
"""

from __future__ import annotations

from backend.skills.providers.agy import AgySkill
from backend.skills.providers.aider import AiderSkill
from backend.skills.providers.claude_code import ClaudeCodeSkill
from backend.skills.providers.codex import CodexSkill
from backend.skills.providers.generic import GenericSkill
from backend.skills.providers.kimi import KimiSkill
from backend.skills.providers.vibe import VibeSkill

__all__ = [
    "AgySkill",
    "AiderSkill",
    "ClaudeCodeSkill",
    "CodexSkill",
    "GenericSkill",
    "KimiSkill",
    "VibeSkill",
]
