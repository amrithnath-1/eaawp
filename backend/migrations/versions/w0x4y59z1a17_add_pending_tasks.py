"""add_pending_tasks

Revision ID: w0x4y59z1a17
Revises: v9w3x48y0z16
Create Date: 2026-10-21 12:00:00.000000

A request that is waiting for an integration to be set up, so it can be
resumed afterwards.  New table only; no existing data is touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w0x4y59z1a17"
down_revision: Union[str, None] = "v9w3x48y0z16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("role_name", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="waiting_setup"),
        sa.Column("requirement_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("blocking_state", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("resumed_plan_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pending_tasks_tenant_id", "pending_tasks", ["tenant_id"])
    op.create_index("ix_pending_tasks_user_id", "pending_tasks", ["user_id"])
    op.create_index("ix_pending_tasks_tenant_status", "pending_tasks", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_pending_tasks_tenant_status", table_name="pending_tasks")
    op.drop_index("ix_pending_tasks_user_id", table_name="pending_tasks")
    op.drop_index("ix_pending_tasks_tenant_id", table_name="pending_tasks")
    op.drop_table("pending_tasks")
