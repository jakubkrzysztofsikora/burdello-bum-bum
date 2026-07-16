"""One-shot cleanup: remove low-level artifacts that are not high-level deliverables.

The new artifact taxonomy only keeps durable deliverables: research, plans,
HTML exports, decks, documents, links, reports, diagrams, specs, and findings.
This script retroactively deletes artifacts that look like routine source files,
tests, configs, snippets, or other low-confidence noise.

Run from inside the bb-backend container (or any env with DB access):
    python -m backend.scripts.cleanup_artifacts            # apply
    python -m backend.scripts.cleanup_artifacts --dry-run  # preview counts
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys

from sqlalchemy import delete, select

from backend.core.database import AsyncSessionLocal
from backend.core.models import Artifact
from backend.core.schemas import ARTIFACT_TYPES

log = logging.getLogger("cleanup_artifacts")

# File extensions and name patterns that strongly indicate routine code/config.
_ROUTINE_EXTENSIONS = frozenset(
    [
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".scala",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".m",
        ".mm",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".cmd",
        ".sql",
        ".test.js",
        ".test.ts",
        ".test.jsx",
        ".test.tsx",
        ".spec.js",
        ".spec.ts",
        ".spec.jsx",
        ".spec.tsx",
        ".test.py",
        ".spec.py",
    ]
)

_ROUTINE_NAME_PATTERNS = [
    re.compile(r"package-lock\.json$", re.IGNORECASE),
    re.compile(r"yarn\.lock$", re.IGNORECASE),
    re.compile(r"Pipfile\.lock$", re.IGNORECASE),
    re.compile(r"poetry\.lock$", re.IGNORECASE),
    re.compile(r"\.env(\.[a-z]+)?$", re.IGNORECASE),
    re.compile(r"\.gitignore$", re.IGNORECASE),
    re.compile(r"\.dockerignore$", re.IGNORECASE),
    re.compile(r"tsconfig.*\.json$", re.IGNORECASE),
    re.compile(r"eslint.*\.(js|json|cjs|mjs)$", re.IGNORECASE),
    re.compile(r"prettier.*\.(js|json|cjs|mjs)$", re.IGNORECASE),
    re.compile(r"vite\.config\.(js|ts|mjs)$", re.IGNORECASE),
    re.compile(r"webpack\.config\.(js|ts|mjs)$", re.IGNORECASE),
    re.compile(r"jest\.config\.(js|ts|json)$", re.IGNORECASE),
    re.compile(r"pytest\.ini$", re.IGNORECASE),
    re.compile(r"setup\.py$", re.IGNORECASE),
    re.compile(r"setup\.cfg$", re.IGNORECASE),
    re.compile(r"pyproject\.toml$", re.IGNORECASE),
    re.compile(r"requirements.*\.txt$", re.IGNORECASE),
    re.compile(r"Dockerfile$", re.IGNORECASE),
    re.compile(r"docker-compose.*\.ya?ml$", re.IGNORECASE),
]

# Old artifact types that are now considered routine noise.
_ROUTINE_TYPES = frozenset(
    ["source_code", "config", "test", "script", "schema", "other", "snippet"]
)


def _is_routine(artifact: Artifact) -> bool:
    """Return True if the artifact should be removed."""
    art_type = (artifact.artifact_type or "").lower().strip()

    # Explicitly curated types are always kept.
    if art_type in ARTIFACT_TYPES:
        return False

    # Explicitly routine types are always removed.
    if art_type in _ROUTINE_TYPES:
        return True

    confidence = 0.0
    if isinstance(artifact.metadata_, dict):
        confidence = float(artifact.metadata_.get("confidence") or 0.0)
    if confidence < 0.6:
        return True

    name = artifact.name or ""
    file_path = ""
    if isinstance(artifact.content, dict):
        file_path = str(artifact.content.get("file_path") or "")

    for text in (name, file_path):
        lower = text.lower()
        for ext in _ROUTINE_EXTENSIONS:
            if lower.endswith(ext):
                return True
        for pattern in _ROUTINE_NAME_PATTERNS:
            if pattern.search(text):
                return True

    return False


async def main(dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Artifact))
        artifacts = list(result.scalars().all())

        to_remove = [a for a in artifacts if _is_routine(a)]
        to_keep = [a for a in artifacts if not _is_routine(a)]

        log.info("Total artifacts: %d", len(artifacts))
        log.info("Would keep: %d", len(to_keep))
        log.info("Would remove: %d", len(to_remove))

        if dry_run:
            log.info("DRY-RUN; no writes.")
            return 0

        if not to_remove:
            log.info("Nothing to remove.")
            return 0

        removed_ids = [artifact.id for artifact in to_remove]
        await db.execute(delete(Artifact).where(Artifact.id.in_(removed_ids)))
        await db.commit()
        log.info("Removed %d low-level artifacts.", len(removed_ids))

    return 0


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many rows would be removed; no DB writes",
    )
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
