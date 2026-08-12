"""Re-dispatch transcripts stuck in ``processing`` directly into ``chunk_embed_task``.

A worker restart can lose in-flight chain jobs while the parent transcript stays
``processing`` (there is no beat-based rescan). Worse, re-running ``process_source``
does NOT recover stale-hash orphans: ``normalize_task`` dedups by the *current* on-disk
file hash, and for a transcript whose source file was later modified that hash now
matches a different, already-``completed`` transcript, so the wedge is never resumed.

This script bypasses the hash-based gate entirely and dispatches
``chunk_embed_task`` straight to the wedged transcript's ID with ``resume: True``.
``chunk_embed_task`` embeds any existing shells and falls back to full chunking
when none exist, so no state is lost. Embedding runs in time-bounded batches
(see ``BB_EMBED_TIME_BUDGET_SECONDS``), so even huge transcripts stay well under
the 1-hour ``task_time_limit`` instead of wedging a worker slot forever — the
size skip is no longer needed.

Usage:
    python -m backend.scripts.resume_stuck [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.core.models import Source, Transcript

logger = logging.getLogger(__name__)


async def resume(dry_run: bool) -> int:
    from backend.pipeline.tasks import chunk_embed_task

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Transcript.id)
                .join(Source, Source.id == Transcript.source_id)
                .where(Transcript.status == "processing")
            )
        ).scalars().all()

    logger.info("found %d stuck processing transcripts", len(rows))
    dispatched = 0
    for transcript_id in rows:
        if dry_run:
            logger.info("[dry-run] would dispatch chunk_embed for %s", transcript_id)
            continue
        chunk_embed_task.delay({"transcript_id": str(transcript_id), "resume": True})
        dispatched += 1
        logger.info("dispatched chunk_embed for %s", transcript_id)
    return dispatched


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-dispatch stuck processing transcripts")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(resume(args.dry_run))


if __name__ == "__main__":
    main()