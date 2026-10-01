"""add_config_change_proposals

Revision ID: b7e4d19c2a85
Revises: a3f2c8e91d04
Create Date: 2026-09-11 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e4d19c2a85"
down_revision: Union[str, None] = "a3f2c8e91d04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "config_change_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("original_instruction", sa.Text(), nullable=False),
        sa.Column("interpreted_intent", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposed_changes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("patch_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("validation_errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("validation_warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("approval_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(length=128), nullable=False, server_default="admin"),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("config_change_proposals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_config_change_proposals_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_config_change_proposals_role_key"), ["role_key"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_config_change_proposals_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("config_change_proposals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_config_change_proposals_created_at"))
        batch_op.drop_index(batch_op.f("ix_config_change_proposals_role_key"))
        batch_op.drop_index(batch_op.f("ix_config_change_proposals_tenant_id"))
    op.drop_table("config_change_proposals")
