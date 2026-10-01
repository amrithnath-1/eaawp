"""add_content_tables

Revision ID: m0j4h59k1i87
Revises: l9i3g48j0h76
Create Date: 2026-09-12 20:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "m0j4h59k1i87"
down_revision: Union[str, None] = "l9i3g48j0h76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("channel", sa.String(64), nullable=False, server_default=""),
        sa.Column("brief_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("campaign_id", sa.String(36), nullable=True),
        sa.Column("objective_id", sa.String(36), nullable=True),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("rag_sources_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("analysis_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("content_items") as b:
        b.create_index(b.f("ix_content_items_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_content_items_created_at"), ["created_at"])


def downgrade() -> None:
    with op.batch_alter_table("content_items") as b:
        b.drop_index(b.f("ix_content_items_created_at"))
        b.drop_index(b.f("ix_content_items_tenant_id"))
    op.drop_table("content_items")
