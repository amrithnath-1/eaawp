"""add_workflow_runs

Revision ID: x1y5z60a2b18
Revises: w0x4y59z1a17
Create Date: 2026-10-21 18:00:00.000000

Persistent workflow run history (duplicate-run prevention, retries, restart
recovery) and per-workflow run settings.  Additive only: a new table and new
nullable/defaulted columns; no existing data is changed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x1y5z60a2b18"
down_revision: Union[str, None] = "w0x4y59z1a17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("role_name", sa.String(length=128), nullable=True))
    op.add_column("workflows", sa.Column("run_as_user_id", sa.String(length=36), nullable=True))
    op.add_column("workflows", sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"))
    op.add_column("workflows", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("workflows", sa.Column("retry_delay_minutes", sa.Integer(), nullable=False, server_default="15"))

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("slot", sa.String(length=80), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_id", sa.String(length=36), nullable=True),
        sa.Column("pending_task_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_by", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workflow_id", "slot", name="uq_workflow_run_slot"),
    )
    op.create_index("ix_workflow_runs_tenant_id", "workflow_runs", ["tenant_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_tenant_status", "workflow_runs", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_tenant_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_tenant_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    with op.batch_alter_table("workflows") as batch:
        batch.drop_column("retry_delay_minutes")
        batch.drop_column("max_retries")
        batch.drop_column("timezone")
        batch.drop_column("run_as_user_id")
        batch.drop_column("role_name")
