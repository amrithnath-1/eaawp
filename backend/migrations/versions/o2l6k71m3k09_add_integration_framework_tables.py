"""add_integration_framework_tables

Revision ID: o2l6k71m3k09
Revises: n1k5j60l2j98
Create Date: 2026-09-21 10:00:00.000000

Adds the two new tables for the Phase 2 Dynamic Integration Framework:

    integration_catalog  — generic provider-agnostic integration records
    capability_grants    — per-(integration, role, capability) access control

These tables extend the platform without replacing the existing
data_connections, external_integrations, or marketing_channel_integrations
tables, which continue to operate unchanged.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o2l6k71m3k09"
down_revision: Union[str, None] = "n1k5j60l2j98"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── integration_catalog ───────────────────────────────────────────────────
    op.create_table(
        "integration_catalog",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "encrypted_credentials", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default="not_configured"
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default="0"
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "account_info_json", sa.Text(), nullable=False, server_default="{}"
        ),
        sa.Column("legacy_connection_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_by", sa.String(length=128), nullable=False,
            server_default="admin"
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("integration_catalog", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_integration_catalog_tenant_id"),
            ["tenant_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_integration_catalog_provider_type"),
            ["provider_type"],
            unique=False,
        )

    # ── capability_grants ─────────────────────────────────────────────────────
    op.create_table(
        "capability_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("capability_key", sa.String(length=128), nullable=False),
        sa.Column("is_granted", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "granted_by", sa.String(length=128), nullable=False,
            server_default="admin"
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integration_catalog.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id", "role_key", "capability_key",
            name="uq_capability_grant_integration_role_cap",
        ),
    )
    with op.batch_alter_table("capability_grants", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_capability_grants_tenant_id"),
            ["tenant_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_capability_grants_integration_id"),
            ["integration_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_capability_grants_role_key"),
            ["role_key"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("capability_grants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_capability_grants_role_key"))
        batch_op.drop_index(batch_op.f("ix_capability_grants_integration_id"))
        batch_op.drop_index(batch_op.f("ix_capability_grants_tenant_id"))
    op.drop_table("capability_grants")

    with op.batch_alter_table("integration_catalog", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_integration_catalog_provider_type"))
        batch_op.drop_index(batch_op.f("ix_integration_catalog_tenant_id"))
    op.drop_table("integration_catalog")
