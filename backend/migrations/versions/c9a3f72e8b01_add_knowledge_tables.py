"""add_knowledge_tables

Revision ID: c9a3f72e8b01
Revises: b7e4d19c2a85
Create Date: 2026-09-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9a3f72e8b01"
down_revision: Union[str, None] = "b7e4d19c2a85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("access_level", sa.String(length=32), nullable=False, server_default="All staff"),
        sa.Column("role_scope", sa.String(length=128), nullable=False, server_default="Global / Shared"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="uploading"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.String(length=128), nullable=False, server_default="admin"),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_knowledge_documents_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_knowledge_documents_uploaded_at"), ["uploaded_at"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("role_scope", sa.String(length=128), nullable=False, server_default="Global / Shared"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("document_chunks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_chunks_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_document_chunks_tenant_id"), ["tenant_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("document_chunks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_chunks_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_document_chunks_document_id"))
    op.drop_table("document_chunks")
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_documents_uploaded_at"))
        batch_op.drop_index(batch_op.f("ix_knowledge_documents_tenant_id"))
    op.drop_table("knowledge_documents")
