"""add_datasets_and_analysis_reports

Revision ID: a4b8c93d5e21
Revises: z3a7b82c4d20
Create Date: 2026-10-21 21:00:00.000000

Data Analyst role: uploaded datasets and saved analysis reports. Additive only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b8c93d5e21"
down_revision: Union[str, None] = "z3a7b82c4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("content_csv", sa.Text(), nullable=False, server_default=""),
        sa.Column("columns_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(36), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_datasets_tenant_id", "datasets", ["tenant_id"])
    op.create_index("ix_datasets_tenant_name", "datasets", ["tenant_id", "name"])

    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(36), nullable=True),
        sa.Column("dataset_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("spec_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("narrative", sa.Text(), nullable=False, server_default=""),
        sa.Column("narrative_source", sa.String(16), nullable=False, server_default="template"),
        sa.Column("is_restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(36), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_analysis_reports_tenant_id", "analysis_reports", ["tenant_id"])
    op.create_index("ix_analysis_reports_dataset_id", "analysis_reports", ["dataset_id"])


def downgrade() -> None:
    op.drop_table("analysis_reports")
    op.drop_table("datasets")
