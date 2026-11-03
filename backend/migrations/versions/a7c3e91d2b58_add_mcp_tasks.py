"""add_mcp_tasks

Revision ID: a7c3e91d2b58
Revises: f5a0b27c8d46
Create Date: 2026-11-03 12:00:00.000000

Long-running MCP operations (jobs) and their lifecycle. Additive: one new table; no existing table or row changes.
Downgrade drops only this table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91d2b58"
down_revision: Union[str, None] = "f5a0b27c8d46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "toolhub_mcp_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=True),
        sa.Column("start_tool", sa.String(128), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("args_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("mechanism", sa.String(16), nullable=False, server_default="tool"),
        sa.Column("status_tool", sa.String(128), nullable=True),
        sa.Column("status_param", sa.String(64), nullable=True),
        sa.Column("cancel_tool", sa.String(128), nullable=True),
        sa.Column("remote_id", sa.String(255), nullable=False),
        sa.Column("remote_id_field", sa.String(64), nullable=False, server_default="id"),
        sa.Column("state", sa.String(16), nullable=False, server_default="CREATED"),
        sa.Column("remote_status", sa.String(64), nullable=True),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("poll_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_poll_error", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_toolhub_tasks_tenant_time", "toolhub_mcp_tasks", ["tenant_id", "created_at"])
    op.create_index("ix_toolhub_tasks_state_poll", "toolhub_mcp_tasks", ["state", "next_poll_at"])
    op.create_index("ix_toolhub_tasks_dedupe", "toolhub_mcp_tasks",
                    ["tenant_id", "integration_id", "start_tool", "args_hash"])


def downgrade() -> None:
    op.drop_index("ix_toolhub_tasks_dedupe", table_name="toolhub_mcp_tasks")
    op.drop_index("ix_toolhub_tasks_state_poll", table_name="toolhub_mcp_tasks")
    op.drop_index("ix_toolhub_tasks_tenant_time", table_name="toolhub_mcp_tasks")
    op.drop_table("toolhub_mcp_tasks")
