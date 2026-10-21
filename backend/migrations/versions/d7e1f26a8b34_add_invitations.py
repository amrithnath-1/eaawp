"""add_invitations

Revision ID: d7e1f26a8b34
Revises: c6d0e15f7a23
Create Date: 2026-10-22 00:30:00.000000

Team invitations (Phase J). Additive only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e1f26a8b34"
down_revision: Union[str, None] = "c6d0e15f7a23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(64), nullable=False, server_default="Employee"),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("invited_by", sa.String(36), nullable=False, server_default=""),
        sa.Column("invited_by_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])


def downgrade() -> None:
    op.drop_index("ix_invitations_tenant_email", table_name="invitations")
    op.drop_index("ix_invitations_tenant_id", table_name="invitations")
    op.drop_table("invitations")
