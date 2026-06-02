"""Source file discovery from provider directories.

Provides ``SourceDiscovery`` which scans well-known directory patterns for
transcript files from various AI session providers (Claude Code, Codex,
Kimi, etc.).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mapping of provider name -> glob pattern (relative to home directory)
DEFAULT_PROVIDER_PATTERNS: dict[str, str] = {
    "claude_code": "**/.claude/projects/**/*.jsonl",
    "codex": "**/.codex/sessions/**/*.jsonl",
    "kimi": "**/.kimi/sessions/**/wire.jsonl",
    "vibe": "**/.vibe/logs/session/*.json",
    "agy": "**/.gemini/antigravity-cli/**/*.jsonl",
    "aider": "**/.aider.chat.history.md",
}


class SourceDiscovery:
    """Discovers transcript files from provider directories.

    Scans the filesystem using per-provider glob patterns and returns
    metadata for each discovered file including a SHA-256 content hash.
    """

    def __init__(
        self,
        base_dirs: dict[str, str] | None = None,
    ) -> None:
        """Initialise the discovery scanner.

        Args:
            base_dirs: Optional mapping of provider name to a directory
                override.  If a provider is not present here, the user's
                home directory is used as the base.
        """
        self.base_dirs = base_dirs or {}
        self.patterns = DEFAULT_PROVIDER_PATTERNS

    def discover(self) -> list[dict[str, Any]]:
        """Discover all transcript files matching provider patterns.

        Returns:
            List of dicts with keys ``path``, ``provider``, ``size``, ``hash``.
        """
        discovered: list[dict[str, Any]] = []

        for provider, pattern in self.patterns.items():
            base_dir = self._resolve_base_dir(provider)
            if base_dir is None:
                continue

            try:
                matches = list(Path(base_dir).glob(pattern))
            except (OSError, PermissionError) as exc:
                logger.warning(
                    "discover: error scanning %s for %s: %s",
                    base_dir,
                    provider,
                    exc,
                )
                continue

            for path in matches:
                if not path.is_file():
                    continue

                try:
                    file_hash = self.compute_hash(path)
                    discovered.append(
                        {
                            "path": str(path.resolve()),
                            "provider": provider,
                            "size": path.stat().st_size,
                            "hash": file_hash,
                        }
                    )
                except (OSError, PermissionError) as exc:
                    logger.warning(
                        "discover: error hashing %s: %s", path, exc
                    )

        logger.info("discover: found %d source files", len(discovered))
        return discovered

    def compute_hash(self, path: Path) -> str:
        """Compute the SHA-256 hash of a file's contents.

        Args:
            path: Path to the file.

        Returns:
            Lowercase hex digest of the SHA-256 hash.
        """
        sha256 = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest().lower()

    def _resolve_base_dir(self, provider: str) -> str | None:
        """Resolve the base directory for a provider.

        Checks ``base_dirs`` override first, then falls back to the
        ``HOME`` / ``USERPROFILE`` environment variable.

        Args:
            provider: Provider identifier.

        Returns:
            Absolute path to the base directory, or ``None`` if unavailable.
        """
        if provider in self.base_dirs:
            return self.base_dirs[provider]

        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        if not home:
            logger.warning(
                "discover: no home directory found for provider %s", provider
            )
            return None

        return home
