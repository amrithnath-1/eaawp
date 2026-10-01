"""add_planning_tables

Revision ID: g4d8b93e5c21
Revises: f3c7a82e4d15
Create Date: 2026-09-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g4d8b93e5c21"
down_revision: Union[str, None] = "f3c7a82e4d15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="planning"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("blueprint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("execution_plans", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_execution_plans_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_execution_plans_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "plan_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step_type", sa.String(length=16), nullable=False, server_default="read"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("arguments_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("depends_on_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("result_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("action_audit_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["execution_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plan_steps", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_plan_steps_plan_id"), ["plan_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_plan_steps_tenant_id"), ["tenant_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("plan_steps", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plan_steps_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_plan_steps_plan_id"))
    op.drop_table("plan_steps")
    with op.batch_alter_table("execution_plans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_execution_plans_created_at"))
        batch_op.drop_index(batch_op.f("ix_execution_plans_tenant_id"))
    op.drop_table("execution_plans")
