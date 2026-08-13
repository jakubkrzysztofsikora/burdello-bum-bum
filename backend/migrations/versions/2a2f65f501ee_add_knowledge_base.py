"""add knowledge base (kb_nodes, kb_node_sources, kb_entities, kb_entity_mentions)

Revision ID: 2a2f65f501ee
Revises: 25bbb833544d
Create Date: 2026-08-13 00:00:00.000000

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
revision: str = '2a2f65f501ee'
down_revision: Union[str, Sequence[str], None] = '25bbb833544d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (idempotent)."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # --- kb_nodes (tree) ---
    if not insp.has_table("kb_nodes"):
        op.create_table(
            "kb_nodes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column(
                "node_type",
                sa.String(length=32),
                nullable=False,
                server_default="topic",
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("embedding", postgresql.Vector(768), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("mechanical_key", sa.String(length=500), nullable=True),
            sa.Column(
                "top_terms", postgresql.ARRAY(sa.String()), nullable=True
            ),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "source_evidence_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
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
                ["parent_id"], ["kb_nodes.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_kb_nodes_slug"),
            sa.UniqueConstraint(
                "mechanical_key", name="uq_kb_nodes_mechanical_key"
            ),
        )
        op.create_index(
            "ix_kb_nodes_parent_id", "kb_nodes", ["parent_id"]
        )
        op.create_index("ix_kb_nodes_status", "kb_nodes", ["status"])

    # --- kb_node_sources ---
    if not insp.has_table("kb_node_sources"):
        op.create_table(
            "kb_node_sources",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "transcript_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("excerpt", sa.Text(), nullable=True),
            sa.Column(
                "evidence_type",
                sa.String(length=32),
                nullable=False,
                server_default="worked_example",
            ),
            sa.Column("outcome", sa.String(length=16), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
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
                ["node_id"], ["kb_nodes.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["transcript_id"], ["transcripts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["chunk_id"], ["chunks.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "node_id",
                "chunk_id",
                name="uq_kb_node_sources_node_chunk",
            ),
        )
        op.create_index(
            "ix_kb_node_sources_node_id", "kb_node_sources", ["node_id"]
        )
        op.create_index(
            "ix_kb_node_sources_transcript_id",
            "kb_node_sources",
            ["transcript_id"],
        )
        op.create_index(
            "ix_kb_node_sources_project_id",
            "kb_node_sources",
            ["project_id"],
        )

    # --- kb_entities ---
    if not insp.has_table("kb_entities"):
        op.create_table(
            "kb_entities",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("canonical_name", sa.String(length=500), nullable=False),
            sa.Column(
                "aliases", postgresql.ARRAY(sa.String()), nullable=True
            ),
            sa.Column(
                "entity_type",
                sa.String(length=32),
                nullable=False,
                server_default="tool",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("how_used", sa.Text(), nullable=True),
            sa.Column("why_used", sa.Text(), nullable=True),
            sa.Column(
                "mention_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("embedding", postgresql.Vector(768), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "canonical_name", name="uq_kb_entities_canonical_name"
            ),
        )

    # --- kb_entity_mentions ---
    if not insp.has_table("kb_entity_mentions"):
        op.create_table(
            "kb_entity_mentions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "entity_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "transcript_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("context_excerpt", sa.Text(), nullable=True),
            sa.Column("outcome", sa.String(length=16), nullable=True),
            sa.Column(
                "first_seen_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column(
                "last_seen_at", sa.DateTime(timezone=True), nullable=True
            ),
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
                ["entity_id"], ["kb_entities.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["node_id"], ["kb_nodes.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["transcript_id"], ["transcripts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["chunk_id"], ["chunks.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "entity_id",
                "chunk_id",
                name="uq_kb_entity_mentions_entity_chunk",
            ),
        )
        op.create_index(
            "ix_kb_entity_mentions_entity_id",
            "kb_entity_mentions",
            ["entity_id"],
        )
        op.create_index(
            "ix_kb_entity_mentions_node_id",
            "kb_entity_mentions",
            ["node_id"],
        )
        op.create_index(
            "ix_kb_entity_mentions_transcript_id",
            "kb_entity_mentions",
            ["transcript_id"],
        )
        op.create_index(
            "ix_kb_entity_mentions_project_id",
            "kb_entity_mentions",
            ["project_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if insp.has_table("kb_entity_mentions"):
        op.drop_index(
            "ix_kb_entity_mentions_project_id",
            table_name="kb_entity_mentions",
        )
        op.drop_index(
            "ix_kb_entity_mentions_transcript_id",
            table_name="kb_entity_mentions",
        )
        op.drop_index(
            "ix_kb_entity_mentions_node_id", table_name="kb_entity_mentions"
        )
        op.drop_index(
            "ix_kb_entity_mentions_entity_id",
            table_name="kb_entity_mentions",
        )
        op.drop_table("kb_entity_mentions")

    if insp.has_table("kb_entities"):
        op.drop_table("kb_entities")

    if insp.has_table("kb_node_sources"):
        op.drop_index(
            "ix_kb_node_sources_project_id", table_name="kb_node_sources"
        )
        op.drop_index(
            "ix_kb_node_sources_transcript_id", table_name="kb_node_sources"
        )
        op.drop_index(
            "ix_kb_node_sources_node_id", table_name="kb_node_sources"
        )
        op.drop_table("kb_node_sources")

    if insp.has_table("kb_nodes"):
        op.drop_index("ix_kb_nodes_status", table_name="kb_nodes")
        op.drop_index("ix_kb_nodes_parent_id", table_name="kb_nodes")
        op.drop_table("kb_nodes")
