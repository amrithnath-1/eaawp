"""add_memory_notification_channel_tables

Revision ID: n1k5j60l2j98
Revises: m0j4h59k1i87
Create Date: 2026-09-13 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "n1k5j60l2j98"
down_revision: Union[str, None] = "m0j4h59k1i87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False, server_default="DIGITAL_MARKETING_MANAGER"),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_memories") as b:
        b.create_index(b.f("ix_agent_memories_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_agent_memories_category"), ["category"])
        b.create_index(b.f("ix_agent_memories_created_at"), ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("category", sa.String(64), nullable=False, server_default="agent_decision"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("related_id", sa.String(36), nullable=True),
        sa.Column("related_type", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notifications") as b:
        b.create_index(b.f("ix_notifications_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_notifications_created_at"), ["created_at"])

    op.create_table(
        "marketing_channel_integrations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("channel_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("provider", sa.String(128), nullable=False, server_default="mock"),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_configured"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False, server_default=""),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("account_info_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("marketing_channel_integrations") as b:
        b.create_index(b.f("ix_marketing_channel_integrations_tenant_id"), ["tenant_id"])


def downgrade() -> None:
    with op.batch_alter_table("marketing_channel_integrations") as b:
        b.drop_index(b.f("ix_marketing_channel_integrations_tenant_id"))
    op.drop_table("marketing_channel_integrations")
    with op.batch_alter_table("notifications") as b:
        b.drop_index(b.f("ix_notifications_created_at"))
        b.drop_index(b.f("ix_notifications_tenant_id"))
    op.drop_table("notifications")
    with op.batch_alter_table("agent_memories") as b:
        b.drop_index(b.f("ix_agent_memories_created_at"))
        b.drop_index(b.f("ix_agent_memories_category"))
        b.drop_index(b.f("ix_agent_memories_tenant_id"))
    op.drop_table("agent_memories")
