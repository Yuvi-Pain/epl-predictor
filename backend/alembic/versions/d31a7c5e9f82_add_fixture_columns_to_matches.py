"""add matchday, kickoff_at and status to matches

Revision ID: d31a7c5e9f82
Revises: b4e8d2a61f37
Create Date: 2026-09-24 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd31a7c5e9f82'
down_revision: Union[str, None] = 'b4e8d2a61f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('matches', sa.Column('matchday', sa.SmallInteger(), nullable=True))
    op.add_column('matches', sa.Column('kickoff_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('status', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('matches', 'status')
    op.drop_column('matches', 'kickoff_at')
    op.drop_column('matches', 'matchday')
