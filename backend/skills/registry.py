"""Skill registry with auto-discovery and conflict resolution.

The :class:`SkillRegistry` maintains an ordered collection of
:class:`~backend.skills.base.TranscriptSkill` subclasses, provides
file-to-skill matching (highest ``can_handle`` wins, ties broken by
lowest ``priority`` number), and exposes a ``discover_builtin_skills``
hook that imports all seven built-in provider skills.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Type

from backend.skills.base import ExtractedTranscript, SkillMetadata, TranscriptSkill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Central registry for :class:`TranscriptSkill` subclasses.

    Skills are stored as **uninstantiated** classes (not instances) so
    that ``can_handle`` and ``metadata`` can be called at class level
    without constructing the skill every time.

    Conflict resolution (in :meth:`get_skill_for_path`) works as follows:

    1. Every registered skill's ``can_handle(path)`` is evaluated.
    2. The skill with the **highest** score wins.
    3. If two skills tie on score, the one with the **lowest** ``priority``
       number (from :class:`SkillMetadata`) wins.
    4. If no skill reports a score > ``0.0``, ``None`` is returned.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._skills: list[Type[TranscriptSkill]] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, skill_cls: Type[TranscriptSkill]) -> None:
        """Register a skill class.

        Args:
            skill_cls: A concrete subclass of :class:`TranscriptSkill`.

        Raises:
            TypeError: If *skill_cls* is not a subclass of
                :class:`TranscriptSkill`.
        """
        if not isinstance(skill_cls, type) or not issubclass(skill_cls, TranscriptSkill):
            raise TypeError(
                f"Expected a TranscriptSkill subclass, got {skill_cls!r}"
            )
        if skill_cls in self._skills:
            logger.debug(
                "Skill %r is already registered, skipping",
                skill_cls.metadata().name,
            )
            return
        self._skills.append(skill_cls)
        logger.debug("Registered skill: %s", skill_cls.metadata().name)

    def unregister(self, skill_cls: Type[TranscriptSkill]) -> None:
        """Remove a skill class from the registry.

        Args:
            skill_cls: The skill class to remove.
        """
        if skill_cls in self._skills:
            self._skills.remove(skill_cls)
            logger.debug("Unregistered skill: %s", skill_cls.metadata().name)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_builtin_skills(self) -> None:
        """Import and register all seven built-in provider skills.

        This is a convenience method that ensures the standard set of
        skills (Claude Code, Codex, Kimi, Vibe, Agy, Aider, Generic) are
        all available without manual imports.
        """
        from backend.skills.providers import (
            AgySkill,
            AiderSkill,
            ClaudeCodeSkill,
            CodexSkill,
            GenericSkill,
            KimiSkill,
            VibeSkill,
        )

        self.register(ClaudeCodeSkill)
        self.register(CodexSkill)
        self.register(KimiSkill)
        self.register(VibeSkill)
        self.register(AgySkill)
        self.register(AiderSkill)
        self.register(GenericSkill)

        logger.info(
            "Discovered and registered %d built-in skills",
            len(self._skills),
        )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_skill_for_path(self, path: Path) -> Optional[Type[TranscriptSkill]]:
        """Find the best skill for *path*.

        Evaluates ``can_handle`` on every registered skill and returns the
        winner using the conflict-resolution rules described in the class
        docstring.

        Args:
            path: File system path to evaluate.

        Returns:
            The winning skill **class**, or ``None`` if no skill can handle
            the path.
        """
        candidates: list[tuple[Type[TranscriptSkill], float]] = []

        for skill_cls in self._skills:
            try:
                score = skill_cls.can_handle(path)
                if score > 0.0:
                    candidates.append((skill_cls, score))
            except Exception:
                logger.exception(
                    "can_handle crashed for %s on %s",
                    skill_cls.metadata().name,
                    path,
                )

        if not candidates:
            return None

        # Sort by score descending, then by priority ascending
        def _sort_key(item: tuple[Type[TranscriptSkill], float]) -> tuple[float, int]:
            skill_cls, score = item
            # Lower priority number = higher priority
            return (-score, skill_cls.metadata().priority)

        candidates.sort(key=_sort_key)
        winner, winner_score = candidates[0]

        logger.debug(
            "Selected skill '%s' (score=%.1f, priority=%d) for %s",
            winner.metadata().name,
            winner_score,
            winner.metadata().priority,
            path,
        )

        return winner

    # ------------------------------------------------------------------
    # Convenience: instantiate + extract
    # ------------------------------------------------------------------

    def extract(
        self,
        path: Path,
        **options: object,
    ) -> list[ExtractedTranscript]:
        """Find the best skill for *path* and extract transcripts.

        This is a one-shot convenience method that combines
        :meth:`get_skill_for_path` with skill instantiation and
        :meth:`~TranscriptSkill.extract_transcripts`.

        Args:
            path: File system path to parse.
            **options: Extra options forwarded to the skill.

        Returns:
            A (possibly empty) list of :class:`ExtractedTranscript` objects.
        """
        skill_cls = self.get_skill_for_path(path)
        if skill_cls is None:
            logger.warning("No skill found for path: %s", path)
            return []

        skill_instance = skill_cls()
        return list(skill_instance.extract_transcripts(path, **options))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for every registered skill.

        Returns:
            Ordered list of :class:`SkillMetadata` objects.
        """
        return [s.metadata() for s in self._skills]

    def get_skill_by_name(self, name: str) -> Optional[Type[TranscriptSkill]]:
        """Look up a registered skill by its metadata name.

        Args:
            name: The ``name`` field from :class:`SkillMetadata`.

        Returns:
            The matching skill class, or ``None``.
        """
        for skill_cls in self._skills:
            if skill_cls.metadata().name == name:
                return skill_cls
        return None

    def __len__(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)

    def __contains__(self, skill_cls: Type[TranscriptSkill]) -> bool:
        """Check whether a skill class is registered."""
        return skill_cls in self._skills

    def __iter__(self):
        """Iterate over registered skill classes."""
        return iter(self._skills)

    def __repr__(self) -> str:
        names = [s.metadata().name for s in self._skills]
        return f"SkillRegistry(skills={names!r})"
