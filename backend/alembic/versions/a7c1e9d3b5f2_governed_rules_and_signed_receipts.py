"""governed rule changes and signed receipts

Revision ID: a7c1e9d3b5f2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-21 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1e9d3b5f2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "policy_proposals" not in tables:
        op.create_table(
            "policy_proposals",
            sa.Column("id", sa.String(), primary_key=True, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="manual"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("base_version", sa.String(), nullable=False),
            sa.Column("changes_json", sa.Text(), nullable=False),
            sa.Column("candidate_params_json", sa.Text(), nullable=False),
            sa.Column("candidate_version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft", index=True),
            sa.Column("evaluation_json", sa.Text(), nullable=True),
            sa.Column("approved_by", sa.String(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approval_note", sa.Text(), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_reason", sa.Text(), nullable=True),
        )

    if "policy_activations" not in tables:
        op.create_table(
            "policy_activations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("version_hash", sa.String(), nullable=False, index=True),
            sa.Column("parameters_json", sa.Text(), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activated_by", sa.String(), nullable=False),
            sa.Column("proposal_id", sa.String(), nullable=True),
            sa.Column("previous_version", sa.String(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
        )

    cols = [c["name"] for c in inspector.get_columns("governance_decisions")]
    with op.batch_alter_table("governance_decisions") as batch_op:
        if "signature" not in cols:
            batch_op.add_column(sa.Column("signature", sa.Text(), nullable=True))
        if "signing_key_id" not in cols:
            batch_op.add_column(sa.Column("signing_key_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("governance_decisions") as batch_op:
        batch_op.drop_column("signing_key_id")
        batch_op.drop_column("signature")
    op.drop_table("policy_activations")
    op.drop_table("policy_proposals")
