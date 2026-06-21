"""One-shot backfill: lift ``session_id`` from transcript JSONB into the column.

Existing transcript rows already carry the agent session UUID inside
``metadata->>'session_id'`` (normalization merges it in at ingest time). Phase 0
promotes that value to an indexed ``transcripts.session_id`` column so bookmarks
can correlate against it. This script copies the JSONB value up for every row
where the column is still NULL, so historical sessions become linkable.

Run from inside the bb-backend container (or any env with DB access):
    python -m backend.scripts.backfill_session_id            # apply
    python -m backend.scripts.backfill_session_id --dry-run  # preview counts
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text

from backend.core.database import AsyncSessionLocal

log = logging.getLogger("backfill_session_id")


async def _pending_count(db) -> int:
    """Number of rows that would be updated by the backfill."""
    return (await db.execute(text(
        "SELECT count(*)::int FROM transcripts "
        "WHERE session_id IS NULL AND metadata->>'session_id' IS NOT NULL"
    ))).scalar_one()


async def main(dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    async with AsyncSessionLocal() as db:
        pending = await _pending_count(db)
        log.info("Rows with session_id in JSONB but NULL column: %d", pending)

        if dry_run:
            log.info("DRY-RUN; no writes.")
            return 0

        async with db.begin():
            r = await db.execute(text(
                "UPDATE transcripts "
                "SET session_id = metadata->>'session_id' "
                "WHERE session_id IS NULL "
                "  AND metadata->>'session_id' IS NOT NULL"
            ))
            updated = r.rowcount or 0
        log.info("Backfilled session_id on %d transcript rows.", updated)

    return 0


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report how many rows would be updated; no DB writes",
    )
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
