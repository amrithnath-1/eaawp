"""add_action_audit_table

Revision ID: f3c7a82e4d15
Revises: e2f6a91d3b07
Create Date: 2026-09-11 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3c7a82e4d15"
down_revision: Union[str, None] = "e2f6a91d3b07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("approval_status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("execution_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("action_audits", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_action_audits_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_action_audits_tool_name"), ["tool_name"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_action_audits_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("action_audits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_action_audits_created_at"))
        batch_op.drop_index(batch_op.f("ix_action_audits_tool_name"))
        batch_op.drop_index(batch_op.f("ix_action_audits_tenant_id"))
    op.drop_table("action_audits")
