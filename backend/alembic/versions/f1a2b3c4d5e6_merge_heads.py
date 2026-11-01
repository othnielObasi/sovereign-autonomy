"""merge migration heads

Revision ID: f1a2b3c4d5e6
Revises: e5f7a8b2c3d4, c3d5e7f9a1b2
Create Date: 2026-03-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = ('e5f7a8b2c3d4', 'c3d5e7f9a1b2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
