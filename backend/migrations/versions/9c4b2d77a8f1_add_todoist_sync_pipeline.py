"""add todoist sync pipeline

Revision ID: 9c4b2d77a8f1
Revises: 25bbb833544d
Create Date: 2026-06-28 12:00:00.000000

Idempotent parity migration for the Todoist sync pipeline tables.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c4b2d77a8f1"
down_revision: Union[str, Sequence[str], None] = "25bbb833544d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if not insp.has_table("todoist_sync_runs"):
        op.create_table(
            "todoist_sync_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="auto"),
            sa.Column("include_done", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("todoist_inbox_project_id", sa.String(length=255), nullable=True),
            sa.Column("plan_data", postgresql.JSONB(), nullable=True),
            sa.Column("result_data", postgresql.JSONB(), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_todoist_sync_runs_project_id", "todoist_sync_runs", ["project_id"])

    if not insp.has_table("todoist_task_links"):
        op.create_table(
            "todoist_task_links",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("epic_key", sa.String(length=255), nullable=False),
            sa.Column("epic_name", sa.String(length=255), nullable=False),
            sa.Column("todoist_project_id", sa.String(length=255), nullable=False),
            sa.Column("todoist_project_name", sa.String(length=255), nullable=False),
            sa.Column("todoist_task_id", sa.String(length=255), nullable=False),
            sa.Column("sync_run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_payload", postgresql.JSONB(), nullable=True),
            sa.Column("last_result", postgresql.JSONB(), nullable=True),
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
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["sync_run_id"], ["todoist_sync_runs.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id"),
            sa.UniqueConstraint("todoist_task_id"),
        )
        op.create_index("ix_todoist_task_links_task_id", "todoist_task_links", ["task_id"])
        op.create_index("ix_todoist_task_links_project_id", "todoist_task_links", ["project_id"])
        op.create_index("ix_todoist_task_links_epic_key", "todoist_task_links", ["epic_key"])
        op.create_index(
            "ix_todoist_task_links_todoist_project_id",
            "todoist_task_links",
            ["todoist_project_id"],
        )
        op.create_index(
            "ix_todoist_task_links_todoist_task_id",
            "todoist_task_links",
            ["todoist_task_id"],
        )
        op.create_index(
            "ix_todoist_task_links_sync_run_id",
            "todoist_task_links",
            ["sync_run_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if insp.has_table("todoist_task_links"):
        op.drop_index("ix_todoist_task_links_sync_run_id", table_name="todoist_task_links")
        op.drop_index("ix_todoist_task_links_todoist_task_id", table_name="todoist_task_links")
        op.drop_index("ix_todoist_task_links_todoist_project_id", table_name="todoist_task_links")
        op.drop_index("ix_todoist_task_links_epic_key", table_name="todoist_task_links")
        op.drop_index("ix_todoist_task_links_project_id", table_name="todoist_task_links")
        op.drop_index("ix_todoist_task_links_task_id", table_name="todoist_task_links")
        op.drop_table("todoist_task_links")

    if insp.has_table("todoist_sync_runs"):
        op.drop_index("ix_todoist_sync_runs_project_id", table_name="todoist_sync_runs")
        op.drop_table("todoist_sync_runs")
