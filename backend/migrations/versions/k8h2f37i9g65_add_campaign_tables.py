"""add_campaign_tables

Revision ID: k8h2f37i9g65
Revises: j7g1e26h8f54
Create Date: 2026-09-12 16:00:00.000000

Creates campaigns and campaign_metrics tables.
These are EAAWP-internal records — separate from any external company database.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "k8h2f37i9g65"
down_revision: Union[str, None] = "j7g1e26h8f54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("target_audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.String(128), nullable=False, server_default=""),
        sa.Column("budget", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.String(32), nullable=True),
        sa.Column("end_date", sa.String(32), nullable=True),
        sa.Column("kpis_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("campaigns") as b:
        b.create_index(b.f("ix_campaigns_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_campaigns_status"), ["status"])
        b.create_index(b.f("ix_campaigns_created_at"), ["created_at"])

    op.create_table(
        "campaign_metrics",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metric_date", sa.String(32), nullable=False, server_default=""),
        sa.Column("source", sa.String(128), nullable=False, server_default="manual"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("recorded_by", sa.String(128), nullable=False, server_default="agent"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("campaign_metrics") as b:
        b.create_index(b.f("ix_campaign_metrics_campaign_id"), ["campaign_id"])
        b.create_index(b.f("ix_campaign_metrics_tenant_id"), ["tenant_id"])
        b.create_index(b.f("ix_campaign_metrics_recorded_at"), ["recorded_at"])


def downgrade() -> None:
    with op.batch_alter_table("campaign_metrics") as b:
        b.drop_index(b.f("ix_campaign_metrics_recorded_at"))
        b.drop_index(b.f("ix_campaign_metrics_tenant_id"))
        b.drop_index(b.f("ix_campaign_metrics_campaign_id"))
    op.drop_table("campaign_metrics")
    with op.batch_alter_table("campaigns") as b:
        b.drop_index(b.f("ix_campaigns_created_at"))
        b.drop_index(b.f("ix_campaigns_status"))
        b.drop_index(b.f("ix_campaigns_tenant_id"))
    op.drop_table("campaigns")
