"""add policy_version to governance_decisions

Revision ID: c3e5f7a9b1d2
Revises: b1f8a7c2d4e6
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e5f7a9b1d2'
down_revision = 'c3e5f8a1b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('governance_decisions', sa.Column('policy_version', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('governance_decisions', 'policy_version')
