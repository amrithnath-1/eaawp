"""add_data_access_tables

Revision ID: e2f6a91d3b07
Revises: d1e5b84f2c39
Create Date: 2026-09-11 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f6a91d3b07"
down_revision: Union[str, None] = "d1e5b84f2c39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_concept", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=255), nullable=False),
        sa.Column("display_label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=128), nullable=False, server_default="admin"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["data_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["schema_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "semantic_concept", "connection_id", "entity_id", "field_name",
            name="uq_semantic_mapping_concept_field"
        ),
    )
    with op.batch_alter_table("semantic_mappings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_semantic_mappings_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_semantic_mappings_semantic_concept"), ["semantic_concept"], unique=False
        )

    op.create_table(
        "data_access_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("entity_name", sa.String(length=255), nullable=True),
        sa.Column("semantic_concept", sa.String(length=128), nullable=True),
        sa.Column("requested_fields_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("filter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("data_access_audits", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_data_access_audits_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_data_access_audits_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("data_access_audits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_access_audits_created_at"))
        batch_op.drop_index(batch_op.f("ix_data_access_audits_tenant_id"))
    op.drop_table("data_access_audits")
    with op.batch_alter_table("semantic_mappings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_semantic_mappings_semantic_concept"))
        batch_op.drop_index(batch_op.f("ix_semantic_mappings_tenant_id"))
    op.drop_table("semantic_mappings")
