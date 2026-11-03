"""add_toolhub

Revision ID: f5a0b27c8d46
Revises: e4f9a16b7c35
Create Date: 2026-11-02 12:00:00.000000

Tool hub: registry of discovered MCP tools and generated internal tools, their versions, role grants, executions, MCP
discovery snapshots and the tool audit trail. Additive: six new tables, no existing data is changed. Downgrade drops
only the new tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a0b27c8d46"
down_revision: Union[str, None] = "e4f9a16b7c35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)


def _now(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "toolhub_tools",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("integration_id", sa.String(36), nullable=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_schema_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("risk_class", sa.String(32), nullable=False, server_default="read_only"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        _now(), _now("updated_at"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "source", "integration_id", "key", name="uq_toolhub_tool"),
    )
    op.create_index("ix_toolhub_tools_tenant_source", "toolhub_tools", ["tenant_id", "source"])

    op.create_table(
        "toolhub_tool_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("toolhub_tools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("code", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_schema_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("tests_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("dependencies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        _now(),
        sa.UniqueConstraint("tool_id", "version", name="uq_toolhub_tool_version"),
    )
    op.create_index("ix_toolhub_versions_tenant", "toolhub_tool_versions", ["tenant_id", "tool_id"])

    op.create_table(
        "toolhub_tool_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("toolhub_tools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("granted_by", sa.String(128), nullable=False, server_default="system"),
        _now(),
        sa.UniqueConstraint("tool_id", "role_key", name="uq_toolhub_grant"),
    )
    op.create_index("ix_toolhub_grants_tenant_role", "toolhub_tool_grants", ["tenant_id", "role_key"])

    op.create_table(
        "toolhub_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("tool_key", sa.String(255), nullable=False),
        sa.Column("tool_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("tool_source", sa.String(16), nullable=False, server_default="builtin"),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_category", sa.String(32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery", sa.Text(), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_summary", sa.Text(), nullable=False, server_default=""),
        _now("started_at"),
    )
    op.create_index("ix_toolhub_exec_tenant_tool", "toolhub_executions", ["tenant_id", "tool_key", "started_at"])
    op.create_index("ix_toolhub_exec_tenant_time", "toolhub_executions", ["tenant_id", "started_at"])

    op.create_table(
        "toolhub_mcp_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("added_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("removed_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("changed_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        _now(),
    )
    op.create_index("ix_toolhub_snap_tenant_integration", "toolhub_mcp_snapshots",
                    ["tenant_id", "integration_id", "created_at"])

    op.create_table(
        "toolhub_events",
        sa.Column("id", sa.String(36), primary_key=True),
        _tenant(),
        sa.Column("tool_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False, server_default="system"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        _now(),
    )
    op.create_index("ix_toolhub_events_tenant_time", "toolhub_events", ["tenant_id", "created_at"])


def downgrade() -> None:
    for name, ix in (("toolhub_events", "ix_toolhub_events_tenant_time"),
                     ("toolhub_mcp_snapshots", "ix_toolhub_snap_tenant_integration"),
                     ("toolhub_executions", "ix_toolhub_exec_tenant_time"),
                     ("toolhub_tool_grants", "ix_toolhub_grants_tenant_role"),
                     ("toolhub_tool_versions", "ix_toolhub_versions_tenant"),
                     ("toolhub_tools", "ix_toolhub_tools_tenant_source")):
        op.drop_index(ix, table_name=name)
        if name == "toolhub_executions":
            op.drop_index("ix_toolhub_exec_tenant_tool", table_name=name)
        op.drop_table(name)
