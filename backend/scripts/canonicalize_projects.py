"""One-shot rebind: replace LLM-derived project rows with deterministic ones.

Strategy (from senior-dev review):
    1. For every Source, resolve its canonical RepoIdentity (Python — needs
       regex / overrides).
    2. COPY the (source_id, canonical_name) pairs into a TEMP TABLE.
    3. INSERT canonical Project rows (idempotent — relies on the unique
       constraint on Project.name).
    4. UPDATE tasks / artifacts via JOIN through transcripts → sources →
       temp table → projects. One UPDATE statement per table.
    5. Global empty-project cleanup.

Everything from step 2 onwards runs in a single transaction so failure leaves
the existing data untouched.

Run from inside the bb-backend container:
    docker exec bb-backend python -m backend.scripts.canonicalize_projects \\
        --dry-run                          # preview without writing
    docker exec bb-backend python -m backend.scripts.canonicalize_projects \\
        --apply                            # actually write
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter

from sqlalchemy import text

from backend.core.database import AsyncSessionLocal
from backend.pipeline.repo_resolver import (
    RepoIdentity,
    counters as resolver_counters,
    resolve_from_path,
    unmatched_slugs,
)

log = logging.getLogger("canonicalize_projects")


async def _load_source_paths(db) -> list[tuple[str, str]]:
    """Return [(source_id_str, file_path), …] for every source row."""
    rows = (await db.execute(text(
        "SELECT id::text, metadata->>'file_path' FROM sources "
        "WHERE metadata->>'file_path' IS NOT NULL"
    ))).all()
    return [(r[0], r[1]) for r in rows]


async def _resolve_pairs(
    source_rows: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], Counter[str]]:
    """Resolve each source's canonical name; return rebind pairs + stats."""
    pairs: list[tuple[str, str]] = []
    stats: Counter[str] = Counter()
    for source_id, file_path in source_rows:
        identity: RepoIdentity | None = resolve_from_path(file_path)
        if identity is None:
            stats["unresolved"] += 1
            continue
        pairs.append((source_id, identity.humanized))
        stats[identity.provider] += 1
    return pairs, stats


async def _apply(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Apply the rebind atomically. Returns counts of affected rows."""
    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # 1. Temp table — uuid for source_id, text for name.
            await db.execute(text(
                "CREATE TEMP TABLE source_rebind ("
                "  source_id uuid PRIMARY KEY, "
                "  canonical_name text NOT NULL"
                ") ON COMMIT DROP"
            ))

            # 2. Bulk insert pairs.
            #    asyncpg can't bind variadic VALUES easily — use executemany.
            await db.execute(
                text(
                    "INSERT INTO source_rebind (source_id, canonical_name) "
                    "VALUES (CAST(:sid AS uuid), :name)"
                ),
                [{"sid": sid, "name": name} for sid, name in pairs],
            )
            counts["rebind_pairs"] = len(pairs)

            # 3. Ensure every canonical project exists.
            r = await db.execute(text(
                "INSERT INTO projects (id, name, status, metadata) "
                "SELECT gen_random_uuid(), canonical_name, 'active', "
                "       jsonb_build_object('confidence', 1.0, 'source', 'resolver') "
                "FROM (SELECT DISTINCT canonical_name FROM source_rebind) d "
                "ON CONFLICT (name) DO NOTHING"
            ))
            counts["projects_inserted"] = r.rowcount or 0

            # 4. Rebind tasks. JOIN chain:
            #    tasks.source_transcript_id → transcripts.id
            #    transcripts.source_id      → sources.id
            #    sources.id                 → source_rebind.source_id
            #    source_rebind.canonical_name → projects.name
            r = await db.execute(text(
                "UPDATE tasks t "
                "SET project_id = p.id "
                "FROM transcripts tr, source_rebind sr, projects p "
                "WHERE t.source_transcript_id = tr.id "
                "  AND tr.source_id = sr.source_id "
                "  AND p.name = sr.canonical_name "
                "  AND (t.project_id IS NULL OR t.project_id <> p.id)"
            ))
            counts["tasks_rebound"] = r.rowcount or 0

            # 5. Rebind artifacts.
            r = await db.execute(text(
                "UPDATE artifacts a "
                "SET project_id = p.id "
                "FROM transcripts tr, source_rebind sr, projects p "
                "WHERE a.source_transcript_id = tr.id "
                "  AND tr.source_id = sr.source_id "
                "  AND p.name = sr.canonical_name "
                "  AND (a.project_id IS NULL OR a.project_id <> p.id)"
            ))
            counts["artifacts_rebound"] = r.rowcount or 0

            # 6a. Detach tasks/artifacts whose source no longer resolves to
            #     any canonical project (blocklisted now / unresolvable). This
            #     turns the legacy POC/Claude-Theme/tmp project rows into
            #     orphans so step 6b can sweep them.
            r = await db.execute(text(
                "UPDATE tasks t SET project_id = NULL "
                "WHERE t.project_id IS NOT NULL "
                "  AND t.source_transcript_id IN ("
                "    SELECT tr.id FROM transcripts tr "
                "    WHERE tr.source_id NOT IN (SELECT source_id FROM source_rebind)"
                "  )"
            ))
            counts["tasks_detached"] = r.rowcount or 0

            r = await db.execute(text(
                "UPDATE artifacts a SET project_id = NULL "
                "WHERE a.project_id IS NOT NULL "
                "  AND a.source_transcript_id IN ("
                "    SELECT tr.id FROM transcripts tr "
                "    WHERE tr.source_id NOT IN (SELECT source_id FROM source_rebind)"
                "  )"
            ))
            counts["artifacts_detached"] = r.rowcount or 0

            # 6b. Global empty-project cleanup.
            r = await db.execute(text(
                "DELETE FROM projects p "
                "WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id) "
                "  AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.project_id = p.id)"
            ))
            counts["projects_dropped"] = r.rowcount or 0

    return counts


async def _summary(db) -> dict[str, int]:
    rows = (await db.execute(text(
        "SELECT count(*)::int FROM projects"
    ))).scalar_one()
    empty_rows = (await db.execute(text(
        "SELECT count(*)::int FROM projects p "
        "WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id) "
        "  AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.project_id = p.id)"
    ))).scalar_one()
    return {"projects_total": rows, "projects_empty": empty_rows}


async def main(dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    async with AsyncSessionLocal() as db:
        before = await _summary(db)
        source_rows = await _load_source_paths(db)

    log.info("Loaded %d source rows; resolving canonical names…", len(source_rows))
    pairs, stats = await _resolve_pairs(source_rows)
    log.info("Resolution stats: %s", dict(stats))
    log.info("Resolver internal counters: %s", resolver_counters())
    unmatched = unmatched_slugs(20)
    if unmatched:
        log.info("Top unmatched slugs (curate via _COLLAPSE_RULES): %s", unmatched)

    distinct_names = sorted({name for _, name in pairs})
    log.info(
        "Would create/use %d distinct canonical projects: %s",
        len(distinct_names),
        distinct_names[:15] + (["…"] if len(distinct_names) > 15 else []),
    )

    if dry_run:
        log.info("DRY-RUN; no writes.")
        log.info("Before: %s", before)
        return 0

    log.info("Applying rebind to %d source→project pairs…", len(pairs))
    counts = await _apply(pairs)
    log.info("Rebind counts: %s", counts)

    async with AsyncSessionLocal() as db:
        after = await _summary(db)
    log.info("Before: %s    After: %s", before, after)
    return 0


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="resolve everything and print the plan; no DB writes")
    g.add_argument("--apply", action="store_true",
                   help="apply the rebind atomically")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
