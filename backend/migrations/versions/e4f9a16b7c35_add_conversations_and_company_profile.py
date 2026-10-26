"""add_conversations_and_company_profile

Revision ID: e4f9a16b7c35
Revises: d3e8f05a6b24
Create Date: 2026-10-25 12:00:00.000000

Persistent AI employee conversations (History) and the administrator-approved company profile. Additive: three new
tables, no existing data is changed. Downgrade drops only the new tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f9a16b7c35"
down_revision: Union[str, None] = "d3e8f05a6b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default="New conversation"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_owner_recent", "conversations", ["tenant_id", "user_id", "updated_at"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("sender", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("plan_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_messages_conv_created", "conversation_messages", ["conversation_id", "created_at"])
    op.create_index("ix_conversation_messages_plan_id", "conversation_messages", ["plan_id"])

    op.create_table(
        "company_profiles",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("company_profiles")
    op.drop_index("ix_conversation_messages_plan_id", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_conv_created", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_owner_recent", table_name="conversations")
    op.drop_table("conversations")
