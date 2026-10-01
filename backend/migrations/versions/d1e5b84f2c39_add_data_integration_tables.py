"""add_data_integration_tables

Revision ID: d1e5b84f2c39
Revises: c9a3f72e8b01
Create Date: 2026-09-11 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e5b84f2c39"
down_revision: Union[str, None] = "c9a3f72e8b01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("db_type", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="5432"),
        sa.Column("database_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("ssl_required", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="not_tested"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("data_connections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_data_connections_tenant_id"), ["tenant_id"], unique=False
        )

    op.create_table(
        "schema_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False, server_default="public"),
        sa.Column("entity_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False, server_default="table"),
        sa.Column("columns_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("row_count_estimate", sa.Integer(), nullable=True),
        sa.Column("is_allowed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["data_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "schema_name", "entity_name",
            name="uq_schema_entity_conn_schema_name"
        ),
    )
    with op.batch_alter_table("schema_entities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_schema_entities_connection_id"), ["connection_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_schema_entities_tenant_id"), ["tenant_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("schema_entities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_schema_entities_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_schema_entities_connection_id"))
    op.drop_table("schema_entities")
    with op.batch_alter_table("data_connections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_data_connections_tenant_id"))
    op.drop_table("data_connections")
