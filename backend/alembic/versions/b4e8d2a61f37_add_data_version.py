"""add data_version

Revision ID: b4e8d2a61f37
Revises: 7c1f3a9e5b20
Create Date: 2026-09-23 20:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e8d2a61f37'
down_revision: Union[str, None] = '7c1f3a9e5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    table = op.create_table('data_version',
    sa.Column('id', sa.SmallInteger(), nullable=False),
    sa.Column('version', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('id = 1', name=op.f('ck_data_version_single_row')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_version'))
    )
    op.bulk_insert(table, [{'id': 1, 'version': 1}])


def downgrade() -> None:
    op.drop_table('data_version')
