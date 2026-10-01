"""add_dynamic_tool_audit_log

Revision ID: p3q7r82s4t10
Revises: o2l6k71m3k09
Create Date: 2026-09-22 10:00:00.000000

Adds the dynamic_tool_audit_logs table for Phase 3.

Every invocation of a Phase 3 dynamic integration tool is recorded here
with safe metadata (no credentials, no raw SQL, no sensitive row data).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p3q7r82s4t10"
down_revision: Union[str, None] = "o2l6k71m3k09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dynamic_tool_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("capability_key", sa.String(length=128), nullable=False),
        sa.Column("tool_key", sa.String(length=255), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("dynamic_tool_audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_dynamic_tool_audit_logs_tenant_id"),
            ["tenant_id"], unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_dynamic_tool_audit_logs_integration_id"),
            ["integration_id"], unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_dynamic_tool_audit_logs_role_key"),
            ["role_key"], unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_dynamic_tool_audit_logs_executed_at"),
            ["executed_at"], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("dynamic_tool_audit_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dynamic_tool_audit_logs_executed_at"))
        batch_op.drop_index(batch_op.f("ix_dynamic_tool_audit_logs_role_key"))
        batch_op.drop_index(batch_op.f("ix_dynamic_tool_audit_logs_integration_id"))
        batch_op.drop_index(batch_op.f("ix_dynamic_tool_audit_logs_tenant_id"))
    op.drop_table("dynamic_tool_audit_logs")
