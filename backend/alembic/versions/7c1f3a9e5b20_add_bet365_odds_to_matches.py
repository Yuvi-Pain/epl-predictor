"""add Bet365 odds to matches

Revision ID: 7c1f3a9e5b20
Revises: 2489841d4332
Create Date: 2026-09-23 18:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c1f3a9e5b20'
down_revision: Union[str, None] = '2489841d4332'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('matches', sa.Column('odds_home', sa.Double(), nullable=True))
    op.add_column('matches', sa.Column('odds_draw', sa.Double(), nullable=True))
    op.add_column('matches', sa.Column('odds_away', sa.Double(), nullable=True))


def downgrade() -> None:
    op.drop_column('matches', 'odds_away')
    op.drop_column('matches', 'odds_draw')
    op.drop_column('matches', 'odds_home')
