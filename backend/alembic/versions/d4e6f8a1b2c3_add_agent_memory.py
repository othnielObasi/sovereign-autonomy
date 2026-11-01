"""add agent_memory table

Revision ID: d4e6f8a1b2c3
Revises: c3e5f7a9b1d2
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e6f8a1b2c3'
down_revision = 'c3e5f7a9b1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_memory',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('content_json', sa.Text(), nullable=False),
        sa.Column('importance', sa.Float(), nullable=False, server_default='0.5'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_memory_run_id', 'agent_memory', ['run_id'])
    op.create_index('ix_agent_memory_category', 'agent_memory', ['category'])
    op.create_index('ix_agent_memory_cat_importance', 'agent_memory', ['category', 'importance'])


def downgrade() -> None:
    op.drop_index('ix_agent_memory_cat_importance', table_name='agent_memory')
    op.drop_index('ix_agent_memory_category', table_name='agent_memory')
    op.drop_index('ix_agent_memory_run_id', table_name='agent_memory')
    op.drop_table('agent_memory')
