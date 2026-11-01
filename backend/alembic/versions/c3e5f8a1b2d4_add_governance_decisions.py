"""add governance decisions table

Revision ID: c3e5f8a1b2d4
Revises: b1f8a7c2d4e6
Create Date: 2026-03-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5f8a1b2d4'
down_revision = 'b1f8a7c2d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'governance_decisions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decision', sa.String(), nullable=False),
        sa.Column('policy_state', sa.String(), nullable=False, server_default='SAFE'),
        sa.Column('risk_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('policy_hits', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('reasons', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('required_action', sa.Text(), nullable=True),
        sa.Column('proposal_intent', sa.String(), nullable=False, server_default='MOVE_TO'),
        sa.Column('proposal_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('telemetry_summary', sa.Text(), nullable=True),
        sa.Column('was_executed', sa.String(), nullable=False, server_default='false'),
        sa.Column('event_hash', sa.String(), nullable=True),
        sa.Column('escalated', sa.String(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_gov_decisions_run_ts', 'governance_decisions', ['run_id', 'ts'])
    op.create_index('ix_gov_decisions_policy_state', 'governance_decisions', ['policy_state'])
    op.create_index('ix_gov_decisions_decision', 'governance_decisions', ['decision'])


def downgrade() -> None:
    op.drop_index('ix_gov_decisions_decision', table_name='governance_decisions')
    op.drop_index('ix_gov_decisions_policy_state', table_name='governance_decisions')
    op.drop_index('ix_gov_decisions_run_ts', table_name='governance_decisions')
    op.drop_table('governance_decisions')
