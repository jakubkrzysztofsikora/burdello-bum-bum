"""add notes tags pinned

Revision ID: 3a0318e8a482
Revises:
Create Date: 2026-06-11 01:22:55.107574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3a0318e8a482'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add columns to projects
    op.add_column('projects', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column('projects', sa.Column('pinned', sa.Boolean(), nullable=False, server_default='false'))

    # Add columns to artifacts
    op.add_column('artifacts', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('artifacts', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column('artifacts', sa.Column('pinned', sa.Boolean(), nullable=False, server_default='false'))

    # Add columns to tasks
    op.add_column('tasks', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('tasks', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column('tasks', sa.Column('pinned', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop columns from tasks
    op.drop_column('tasks', 'pinned')
    op.drop_column('tasks', 'tags')
    op.drop_column('tasks', 'notes')

    # Drop columns from artifacts
    op.drop_column('artifacts', 'pinned')
    op.drop_column('artifacts', 'tags')
    op.drop_column('artifacts', 'notes')

    # Drop columns from projects
    op.drop_column('projects', 'pinned')
    op.drop_column('projects', 'tags')
    op.drop_column('projects', 'notes')
