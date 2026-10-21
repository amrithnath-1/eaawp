"""add_direct_messages

Revision ID: e8f2a37b9c45
Revises: d7e1f26a8b34
Create Date: 2026-10-22 02:00:00.000000

Internal direct messages (Phase J, part 2). Additive only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f2a37b9c45"
down_revision: Union[str, None] = "d7e1f26a8b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "direct_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.String(36), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_direct_messages_tenant_id", "direct_messages", ["tenant_id"])
    op.create_index("ix_dm_pair", "direct_messages", ["tenant_id", "sender_id", "recipient_id"])
    op.create_index("ix_dm_recipient_unread", "direct_messages", ["tenant_id", "recipient_id", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_dm_recipient_unread", table_name="direct_messages")
    op.drop_index("ix_dm_pair", table_name="direct_messages")
    op.drop_index("ix_direct_messages_tenant_id", table_name="direct_messages")
    op.drop_table("direct_messages")
