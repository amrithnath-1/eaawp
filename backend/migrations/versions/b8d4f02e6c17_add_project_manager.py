"""add_project_manager

Revision ID: b8d4f02e6c17
Revises: a7c3e91d2b58
Create Date: 2026-11-06 12:00:00.000000

Project Manager AI employee (ported from Vyuham): one working-state row per company, project documents and their
indexed text. Additive: three new tables; no existing table or row changes. Downgrade drops only these tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f02e6c17"
down_revision: Union[str, None] = "a7c3e91d2b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pm_state",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "pm_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ext", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suspicious_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pm_documents_tenant_project", "pm_documents", ["tenant_id", "project_id"])
    op.create_table(
        "pm_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("pm_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(160), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("suspicious", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_pm_chunks_tenant_project", "pm_chunks", ["tenant_id", "project_id"])
    op.create_index("ix_pm_chunks_document", "pm_chunks", ["document_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_pm_chunks_document", table_name="pm_chunks")
    op.drop_index("ix_pm_chunks_tenant_project", table_name="pm_chunks")
    op.drop_table("pm_chunks")
    op.drop_index("ix_pm_documents_tenant_project", table_name="pm_documents")
    op.drop_table("pm_documents")
    op.drop_table("pm_state")
