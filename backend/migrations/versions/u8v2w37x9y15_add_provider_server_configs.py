"""add_provider_server_configs

Revision ID: u8v2w37x9y15
Revises: t7u1v26w8x14
Create Date: 2026-10-01

Adds provider_server_configs table for the Admin-Assisted Configuration Engine.
Stores Fernet-encrypted server-level provider credentials (e.g. Google OAuth
client_id, client_secret) scoped per tenant.

SECURITY: encrypted_value stores ciphertext only — never plaintext.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "u8v2w37x9y15"
down_revision = "t7u1v26w8x14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_server_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("field_key", sa.String(128), nullable=False),
        sa.Column("encrypted_value", sa.Text, nullable=False),
        sa.Column("configured_by", sa.String(128), nullable=False),
        sa.Column(
            "configured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "provider_type", "field_key",
            name="uq_provider_server_config",
        ),
    )
    op.create_index(
        "ix_provider_server_configs_tenant_id",
        "provider_server_configs",
        ["tenant_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("provider_server_configs")
