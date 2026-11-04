"""add pilot requests

Revision ID: b8d2f4a6c1e3
Revises: a7c1e9d3b5f2
Create Date: 2026-11-04 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8d2f4a6c1e3"
down_revision: Union[str, None] = "a7c1e9d3b5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pilot_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reference", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("organisation", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("site_type", sa.String(), nullable=False),
        sa.Column("fleet_size", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(), nullable=True),
    )
    op.create_index("ix_pilot_requests_created_at", "pilot_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_pilot_requests_created_at", table_name="pilot_requests")
    op.drop_table("pilot_requests")
