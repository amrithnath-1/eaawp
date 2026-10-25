"""add_monitoring_tables

Revision ID: h5e9c04f6d32
Revises: g4d8b93e5c21
Create Date: 2026-09-12 10:00:00.000000

Creates the monitoring_rules and monitoring_audit_logs tables for the
Autonomous Monitoring and Trigger Engine.

Security notes
--------------
- condition_json stores only structured MonitoringCondition data — no SQL.
- monitoring_audit_logs stores only safe metadata (aggregate values, result codes).
  No credentials, raw SQL, row-level company data, or chain-of-thought.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h5e9c04f6d32"
down_revision: Union[str, None] = "g4d8b93e5c21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── monitoring_rules ──────────────────────────────────────────────────────
    op.create_table(
        "monitoring_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("semantic_concept", sa.String(length=128), nullable=False),
        sa.Column("condition_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evaluation_frequency", sa.String(length=32), nullable=False, server_default="daily"),
        sa.Column("action_objective", sa.Text(), nullable=False),
        sa.Column(
            "require_approval_on_trigger",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="idle"),
        sa.Column("last_evaluation_result", sa.String(length=32), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_triggered_plan_id", sa.String(length=36), nullable=True),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("monitoring_rules", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_monitoring_rules_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_monitoring_rules_role_key"), ["role_key"], unique=False
        )

    # ── monitoring_audit_logs ─────────────────────────────────────────────────
    op.create_table(
        "monitoring_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("rule_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("semantic_concept", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("result", sa.String(length=32), nullable=False, server_default="condition_false"),
        sa.Column("triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("triggered_plan_id", sa.String(length=36), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("previous_value", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["monitoring_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("monitoring_audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_monitoring_audit_logs_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_monitoring_audit_logs_rule_id"), ["rule_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_monitoring_audit_logs_evaluated_at"), ["evaluated_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("monitoring_audit_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_monitoring_audit_logs_evaluated_at"))
        batch_op.drop_index(batch_op.f("ix_monitoring_audit_logs_rule_id"))
        batch_op.drop_index(batch_op.f("ix_monitoring_audit_logs_tenant_id"))
    op.drop_table("monitoring_audit_logs")

    with op.batch_alter_table("monitoring_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_monitoring_rules_role_key"))
        batch_op.drop_index(batch_op.f("ix_monitoring_rules_tenant_id"))
    op.drop_table("monitoring_rules")
