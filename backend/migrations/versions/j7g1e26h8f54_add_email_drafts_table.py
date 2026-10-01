"""add_email_drafts_table

Revision ID: j7g1e26h8f54
Revises: i6f0d15g7e43
Create Date: 2026-09-12 14:00:00.000000

Creates email_drafts table — internal only, no external side effects.

Security notes
--------------
- email_drafts stores structured draft content only.
- No SMTP credentials, no authentication tokens.
- Tenant isolated via tenant_id FK.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j7g1e26h8f54"
down_revision: Union[str, None] = "i6f0d15g7e43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("recipients_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("reply_to", sa.String(length=255), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_sources_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("linked_plan_id", sa.String(length=36), nullable=True),
        sa.Column("linked_approval_id", sa.String(length=36), nullable=True),
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
    with op.batch_alter_table("email_drafts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_email_drafts_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_email_drafts_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("email_drafts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_email_drafts_created_at"))
        batch_op.drop_index(batch_op.f("ix_email_drafts_tenant_id"))
    op.drop_table("email_drafts")
