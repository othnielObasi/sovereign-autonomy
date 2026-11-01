"""add operator approvals table

Revision ID: 8f1c3d2a9b24
Revises: 7d94d745f552
Create Date: 2026-02-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f1c3d2a9b24'
down_revision = '7d94d745f552'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'operator_approvals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('proposal_hash', sa.String(), nullable=False),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_operator_approvals_run_id'), 'operator_approvals', ['run_id'], unique=False)
    op.create_index(op.f('ix_operator_approvals_proposal_hash'), 'operator_approvals', ['proposal_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_operator_approvals_proposal_hash'), table_name='operator_approvals')
    op.drop_index(op.f('ix_operator_approvals_run_id'), table_name='operator_approvals')
    op.drop_table('operator_approvals')
