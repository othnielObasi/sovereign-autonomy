"""align mission and audit schema

Revision ID: b1f8a7c2d4e6
Revises: 8f1c3d2a9b24
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b1f8a7c2d4e6"
down_revision: Union[str, Sequence[str], None] = "8f1c3d2a9b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    mission_columns = {column["name"] for column in inspector.get_columns("missions")}
    if "status" not in mission_columns:
        op.add_column("missions", sa.Column("status", sa.String(), nullable=True, server_default="draft"))
        op.execute("UPDATE missions SET status = 'draft' WHERE status IS NULL")
        op.alter_column("missions", "status", existing_type=sa.String(), nullable=False, server_default=None)

    if "updated_at" not in mission_columns:
        op.add_column("missions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    tables = set(inspector.get_table_names())
    if "mission_audit" not in tables:
        op.create_table(
            "mission_audit",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=True),
            sa.Column("old_values", sa.Text(), nullable=True),
            sa.Column("new_values", sa.Text(), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["mission_id"], ["missions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_mission_audit_mission_id"), "mission_audit", ["mission_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "mission_audit" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("mission_audit")}
        index_name = op.f("ix_mission_audit_mission_id")
        if index_name in indexes:
            op.drop_index(index_name, table_name="mission_audit")
        op.drop_table("mission_audit")

    mission_columns = {column["name"] for column in inspector.get_columns("missions")}
    if "updated_at" in mission_columns:
        op.drop_column("missions", "updated_at")
    if "status" in mission_columns:
        op.drop_column("missions", "status")