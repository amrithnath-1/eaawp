"""add_strategy_tables

Revision ID: l9i3g48j0h76
Revises: k8h2f37i9g65
Create Date: 2026-09-12 18:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "l9i3g48j0h76"
down_revision: Union[str, None] = "k8h2f37i9g65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketing_objectives",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("objective_type", sa.String(64), nullable=False, server_default="custom"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("target_metric", sa.String(128), nullable=False, server_default=""),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("start_date", sa.String(32), nullable=True),
        sa.Column("target_date", sa.String(32), nullable=True),
        sa.Column("linked_campaign_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("marketing_objectives") as b:
        b.create_index(b.f("ix_marketing_objectives_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_marketing_objectives_created_at"), ["created_at"])


def downgrade() -> None:
    with op.batch_alter_table("marketing_objectives") as b:
        b.drop_index(b.f("ix_marketing_objectives_created_at"))
        b.drop_index(b.f("ix_marketing_objectives_tenant_id"))
    op.drop_table("marketing_objectives")
