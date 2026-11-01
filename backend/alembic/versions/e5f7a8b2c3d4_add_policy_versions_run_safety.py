"""add policy_versions table and run safety fields

Revision ID: e5f7a8b2c3d4
Revises: d4e6f8a1b2c3
Create Date: 2026-03-24 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5f7a8b2c3d4"
down_revision: Union[str, None] = "d4e6f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create policy_versions table if it doesn't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "policy_versions" not in existing_tables:
        op.create_table(
            "policy_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("version_hash", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("parameters_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
        )

    # Run-level fields for safety validation and versioning
    existing_cols = [c["name"] for c in inspector.get_columns("runs")]
    with op.batch_alter_table("runs") as batch_op:
        if "policy_version" not in existing_cols:
            batch_op.add_column(sa.Column("policy_version", sa.String(), nullable=True))
        if "planning_mode" not in existing_cols:
            batch_op.add_column(sa.Column("planning_mode", sa.String(), nullable=True))
        if "safety_verdict" not in existing_cols:
            batch_op.add_column(sa.Column("safety_verdict", sa.String(), nullable=True))
        if "safety_report_json" not in existing_cols:
            batch_op.add_column(sa.Column("safety_report_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("safety_report_json")
        batch_op.drop_column("safety_verdict")
        batch_op.drop_column("planning_mode")
        batch_op.drop_column("policy_version")
    op.drop_table("policy_versions")
