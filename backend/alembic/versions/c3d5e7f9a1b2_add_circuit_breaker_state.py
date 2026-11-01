"""add circuit breaker state table

Revision ID: c3d5e7f9a1b2
Revises: b1f8a7c2d4e6
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f9a1b2'
down_revision: Union[str, None] = 'b1f8a7c2d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'circuit_breaker_state',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('consecutive_denials', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('escalated', sa.String(), nullable=False, server_default='false'),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_circuit_breaker_run_id', 'circuit_breaker_state', ['run_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_circuit_breaker_run_id', table_name='circuit_breaker_state')
    op.drop_table('circuit_breaker_state')
