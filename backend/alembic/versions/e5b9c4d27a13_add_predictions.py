"""add predictions, frozen once saved

Revision ID: e5b9c4d27a13
Revises: d31a7c5e9f82
Create Date: 2026-09-25 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b9c4d27a13'
down_revision: Union[str, None] = 'd31a7c5e9f82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'predictions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=False),
        sa.Column('model_version', sa.String(length=16), nullable=False),
        sa.Column('p_home', sa.Double(), nullable=False),
        sa.Column('p_draw', sa.Double(), nullable=False),
        sa.Column('p_away', sa.Double(), nullable=False),
        sa.Column(
            'predicted_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            'p_home BETWEEN 0 AND 1 AND p_draw BETWEEN 0 AND 1 AND p_away BETWEEN 0 AND 1',
            name=op.f('ck_predictions_probabilities_in_range'),
        ),
        sa.CheckConstraint(
            'abs(p_home + p_draw + p_away - 1) < 1e-6',
            name=op.f('ck_predictions_probabilities_sum_to_1'),
        ),
        sa.ForeignKeyConstraint(
            ['match_id'], ['matches.id'], name=op.f('fk_predictions_match_id_matches')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_predictions')),
        sa.UniqueConstraint(
            'match_id', 'model_version', name=op.f('uq_predictions_match_id_model_version')
        ),
    )
    op.create_index(op.f('ix_predictions_match_id'), 'predictions', ['match_id'], unique=False)

    # A saved prediction is a record of what the model said before kickoff.
    # Changing or removing one afterwards would rewrite the track record, so
    # the database refuses, whoever asks.
    op.execute(
        """
        CREATE FUNCTION predictions_are_frozen() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'predictions are frozen once saved (% on prediction %)', TG_OP, OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER predictions_frozen
        BEFORE UPDATE OR DELETE ON predictions
        FOR EACH ROW EXECUTE FUNCTION predictions_are_frozen()
        """
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER predictions_frozen ON predictions')
    op.execute('DROP FUNCTION predictions_are_frozen()')
    op.drop_index(op.f('ix_predictions_match_id'), table_name='predictions')
    op.drop_table('predictions')
