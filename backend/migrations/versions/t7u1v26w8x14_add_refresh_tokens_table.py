"""add_refresh_tokens_table

Revision ID: t7u1v26w8x14
Revises: s6t0u15v7w13
Create Date: 2026-09-24

Adds refresh_tokens table for DB-persisted refresh token revocation.
Token hash (SHA-256) stored — never the raw token.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "t7u1v26w8x14"
down_revision = "s6t0u15v7w13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "tenant_id", sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("jti", sa.String(36), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], if_not_exists=True)
    op.create_index("ix_refresh_tokens_tenant_id", "refresh_tokens", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True, if_not_exists=True)


def downgrade() -> None:
    op.drop_table("refresh_tokens")
