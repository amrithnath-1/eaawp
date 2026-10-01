"""add_employee_blueprint_and_workflow_tables

Revision ID: r5s9t04u6v12
Revises: q4r8s93t5u11
Create Date: 2026-09-24

Adds:
  - employee_blueprint_proposals (Phase H — AI Employee Builder)
  - workflows (Phase I — Workflow Engine)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "r5s9t04u6v12"
down_revision = "q4r8s93t5u11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_blueprint_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("purpose", sa.Text, nullable=False, server_default=""),
        sa.Column("responsibilities_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("objectives_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("required_capabilities_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("missing_integrations_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("allowed_tools_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("guarded_tools_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("suggested_schedule", sa.String(100), nullable=True),
        sa.Column("communication_style", sa.String(32), nullable=False, server_default="Concise"),
        sa.Column("llm_model", sa.String(64), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("system_persona", sa.Text, nullable=False, server_default=""),
        sa.Column("original_instruction", sa.Text, nullable=False, server_default=""),
        sa.Column("approval_status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="admin"),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("ai_employee_id", sa.String(36), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ai_employee_id", sa.String(36), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("trigger", sa.String(64), nullable=False, server_default="manual"),
        sa.Column("schedule_cron", sa.String(100), nullable=True),
        sa.Column("steps_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(32), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflows")
    op.drop_table("employee_blueprint_proposals")
