"""Re-dispatch transcripts stuck in ``processing`` directly into ``chunk_embed_task``.

A worker restart can lose in-flight chain jobs while the parent transcript stays
``processing`` (there is no beat-based rescan). Worse, re-running ``process_source``
does NOT recover stale-hash orphans: ``normalize_task`` dedups by the *current* on-disk
file hash, and for a transcript whose source file was later modified that hash now
matches a different, already-``completed`` transcript, so the wedge is never resumed.

This script bypasses the hash-based gate entirely and dispatches
``chunk_embed_task`` straight to the wedged transcript's ID. ``chunk_embed_task`` is
idempotent (it clears prior chunks first), and the transcript already has ``raw_text``,
so only chunking + embedding is missing.

Transcripts with more than ``--max-msgs`` messages are skipped by default:
``chunk_embed_task`` processes a whole transcript synchronously and hits the 1-hour
``task_time_limit`` on huge sessions, then retries forever and wedges all worker
slots. Pass ``--include-large`` to dispatch them anyway.

Usage:
    python -m backend.scripts.resume_stuck [--max-msgs 1500] [--include-large] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import func, select

from backend.core.database import AsyncSessionLocal
from backend.core.models import Message, Source, Transcript

logger = logging.getLogger(__name__)


async def resume(max_msgs: int, include_large: bool, dry_run: bool) -> int:
    from backend.pipeline.tasks import chunk_embed_task

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Transcript, Source.metadata_["file_path"].as_string())
                .join(Source, Source.id == Transcript.source_id)
                .where(Transcript.status == "processing")
            )
        ).all()
        counts = dict(
            (
                await db.execute(
                    select(Message.transcript_id, func.count())
                    .where(Message.transcript_id.in_(r[0].id for r in rows))
                    .group_by(Message.transcript_id)
                )
            ).all()
        )

    logger.info("found %d stuck processing transcripts", len(rows))
    dispatched = 0
    for transcript, path in rows:
        if not include_large and counts.get(transcript.id, 0) > max_msgs:
            if path:
                logger.info("skipping %s (%d msgs > %d)", path, counts.get(transcript.id, 0), max_msgs)
            else:
                logger.info("skipping %s (%d msgs > %d)", transcript.id, counts.get(transcript.id, 0), max_msgs)
            continue
        if dry_run:
            logger.info("[dry-run] would dispatch chunk_embed for %s", transcript.id)
            continue
        chunk_embed_task.delay({"transcript_id": str(transcript.id)})
        dispatched += 1
        logger.info("dispatched chunk_embed for %s (%s)", transcript.id, path)
    return dispatched


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-dispatch stuck processing transcripts")
    parser.add_argument("--max-msgs", type=int, default=1500)
    parser.add_argument("--include-large", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(resume(args.max_msgs, args.include_large, args.dry_run))


if __name__ == "__main__":
    main()