"""Backfill the Knowledge Base from existing transcripts + run a cluster rebuild.

Walks every ``completed`` transcript that does not yet have a
``MiningResult(miner_type='knowledge')`` row, runs the LLM knowledge-extraction
pipeline on it (same code path as ``knowledge_extract_task`` in the
Celery chain), and then triggers ``kb_cluster_task`` synchronously so the
freshly-mined atoms land in the KB tree.

Default scope is **all completed transcripts without knowledge atoms**;
pass ``--limit N`` for a smoke run.

Run from inside the backend container (local compose or k3s pod):

    docker exec bb-backend python -m backend.scripts.build_kb --dry-run
    docker exec bb-backend python -m backend.scripts.build_kb --apply
    docker exec bb-backend python -m backend.scripts.build_kb --apply --limit 5
    docker exec bb-backend python -m backend.scripts.build_kb --apply --only-cluster
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from typing import Any

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.database import AsyncSessionLocal
from backend.core.models import MiningResult, Transcript
from backend.knowledge.task import kb_cluster_task
from backend.mining.engine import MiningEngine
from backend.pipeline.storage import PipelineStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("build_kb")


async def _transcripts_needing_atoms(
    db: Any,
    *,
    limit: int | None,
) -> list[uuid.UUID]:
    """Return completed transcripts that have no knowledge MiningResult yet."""
    rows = (
        await db.execute(
            select(Transcript.id)
            .where(
                Transcript.status == "completed",
                ~select(MiningResult.id)
                .where(
                    MiningResult.transcript_id == Transcript.id,
                    MiningResult.miner_type == "knowledge",
                )
                .exists(),
            )
            .order_by(Transcript.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def _backfill_atoms(
    transcript_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Run extraction for each transcript and persist MiningResult rows.

    Mirrors ``knowledge_extract_task`` so the script and the Celery task
    produce identical output.
    """
    settings = get_settings()
    engine = MiningEngine(litellm_url=settings.LITELLM_URL)

    counts: dict[str, int] = {
        "transcripts_total": len(transcript_ids),
        "extracted_ok": 0,
        "extracted_empty": 0,
        "extraction_failed": 0,
    }

    async with AsyncSessionLocal() as db:
        storage = PipelineStorage(db=db)
        for tid in transcript_ids:
            text = await storage.get_transcript_text(tid)
            if not text:
                counts["extracted_empty"] += 1
                continue
            try:
                atoms = await engine.extract_knowledge(text)
            except Exception as exc:
                log.warning(
                    "extract_knowledge failed for %s: %s — skipping",
                    tid,
                    exc,
                )
                counts["extraction_failed"] += 1
                continue

            if not atoms:
                counts["extracted_empty"] += 1
                continue

            await storage.delete_mining_results_by_type(tid, "knowledge")
            avg_conf = sum(
                float(a.get("confidence") or 0.0) for a in atoms
            ) / len(atoms)
            db.add(
                MiningResult(
                    transcript_id=tid,
                    miner_type="knowledge",
                    result_data={"atoms": atoms},
                    confidence=avg_conf,
                    metadata_={"atom_count": len(atoms)},
                )
            )
            await db.commit()
            counts["extracted_ok"] += 1

    return counts


async def _run(
    *,
    apply: bool,
    limit: int | None,
    only_cluster: bool,
) -> dict[str, Any]:
    if not apply:
        # Dry-run: just count.
        async with AsyncSessionLocal() as db:
            ids = await _transcripts_needing_atoms(db, limit=limit)
            log.info(
                "dry-run: %d completed transcript(s) need knowledge atoms",
                len(ids),
            )
            return {
                "mode": "dry-run",
                "would_backfill": len(ids),
                "would_cluster": bool(ids) or only_cluster,
            }

    counts: dict[str, Any] = {"mode": "apply"}
    if not only_cluster:
        async with AsyncSessionLocal() as db:
            ids = await _transcripts_needing_atoms(db, limit=limit)
        if ids:
            log.info(
                "backfilling knowledge atoms for %d transcript(s)…",
                len(ids),
            )
            counts["backfill"] = await _backfill_atoms(ids)
        else:
            log.info("no transcripts need backfill; skipping extraction")
            counts["backfill"] = {"transcripts_total": 0}

    log.info("running kb_cluster_task synchronously…")
    # kb_cluster_task is bind=True, so ``task.run()`` would mis-bind self.
    # ``task.apply()`` runs eagerly with the correct Celery self binding.
    cluster_result = await asyncio.to_thread(
        lambda: kb_cluster_task.apply().get()
    )
    counts["cluster"] = cluster_result
    log.info("cluster result: %s", cluster_result)
    return counts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="Preview only — no writes, no clustering.",
    )
    g.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="Actually run extraction + clustering.",
    )
    p.set_defaults(apply=False)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max transcripts to backfill (default: all).",
    )
    p.add_argument(
        "--only-cluster",
        action="store_true",
        help="Skip backfill; just run kb_cluster_task.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = asyncio.run(
            _run(
                apply=args.apply,
                limit=args.limit,
                only_cluster=args.only_cluster,
            )
        )
    except Exception:
        log.exception("build_kb failed")
        return 1
    log.info("result: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())