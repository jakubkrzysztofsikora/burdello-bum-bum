"""add bookmarks and transcript session_id

Revision ID: 25bbb833544d
Revises: 3a0318e8a482
Create Date: 2026-06-21 00:00:00.000000

Idempotent / parity migration. The application's authoritative schema path is
``Base.metadata.create_all`` (run on every startup in ``main.py``); this
migration exists for documentation and for boxes where Alembic is run instead.
Every operation is guarded so ``alembic upgrade head`` is a no-op when the app
has already created the objects via ``create_all``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '25bbb833544d'
down_revision: Union[str, Sequence[str], None] = '3a0318e8a482'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (idempotent)."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # --- transcripts.session_id (Phase 0) ---
    transcript_cols = [c["name"] for c in insp.get_columns("transcripts")]
    if "session_id" not in transcript_cols:
        op.add_column(
            "transcripts",
            sa.Column("session_id", sa.String(length=255), nullable=True),
        )
        op.create_index(
            "ix_transcripts_session_id",
            "transcripts",
            ["session_id"],
        )

    # --- bookmarks table (Phase 1) ---
    if not insp.has_table("bookmarks"):
        op.create_table(
            "bookmarks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("session_id", sa.String(length=255), nullable=True),
            sa.Column("session_path", sa.String(length=1000), nullable=True),
            sa.Column("note_text", sa.Text(), nullable=False),
            sa.Column("author", sa.String(length=100), nullable=True),
            sa.Column(
                "ingest_status",
                sa.String(length=20),
                nullable=False,
                server_default="none",
            ),
            sa.Column("ingest_job_id", sa.String(length=255), nullable=True),
            sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column(
                "pinned",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("metadata", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["transcript_id"], ["transcripts.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_bookmarks_session_id", "bookmarks", ["session_id"]
        )
        op.create_index(
            "ix_bookmarks_list",
            "bookmarks",
            ["project_id", "pinned", "created_at"],
        )
        # Partial index for the session_id-keyed linker.
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_bookmarks_unlinked "
            "ON bookmarks (session_id) WHERE transcript_id IS NULL"
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if insp.has_table("bookmarks"):
        op.execute("DROP INDEX IF EXISTS ix_bookmarks_unlinked")
        op.drop_index("ix_bookmarks_list", table_name="bookmarks")
        op.drop_index("ix_bookmarks_session_id", table_name="bookmarks")
        op.drop_table("bookmarks")

    transcript_cols = [c["name"] for c in insp.get_columns("transcripts")]
    if "session_id" in transcript_cols:
        op.drop_index("ix_transcripts_session_id", table_name="transcripts")
        op.drop_column("transcripts", "session_id")
