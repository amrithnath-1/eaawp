"""notification_delivery_and_consent

Revision ID: b1c5d6e72f08
Revises: a0b4c59d1e67
Create Date: 2026-10-22 09:00:00.000000

Phase M (notifications). Additive only: per-recipient notifications, an email outbox status, a company-level
authorization switch (default OFF) and per-person preferences (email default OFF). Existing rows keep working
(user_id NULL = legacy company-wide row, shown to administrators only).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c5d6e72f08"
down_revision: Union[str, None] = "a0b4c59d1e67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("user_id", sa.String(36), nullable=True))
    op.add_column("notifications", sa.Column("email_status", sa.String(16), nullable=False, server_default="none"))
    op.add_column("notifications", sa.Column("email_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_table(
        "notification_settings",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("changed_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "category", name="uq_notification_pref"),
    )
    op.create_index("ix_notification_preferences_tenant_id", "notification_preferences", ["tenant_id"])
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_index("ix_notification_preferences_tenant_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_table("notification_settings")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_user_id")
        batch.drop_column("email_attempts")
        batch.drop_column("email_status")
        batch.drop_column("user_id")
