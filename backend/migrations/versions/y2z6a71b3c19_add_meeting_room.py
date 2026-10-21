"""add_meeting_room

Revision ID: y2z6a71b3c19
Revises: x1y5z60a2b18
Create Date: 2026-10-21 19:00:00.000000

Meeting Room: meetings, delegated meeting tasks and the message log.
Additive only (three new tables); no existing data is touched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y2z6a71b3c19"
down_revision: Union[str, None] = "x1y5z60a2b18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk(col, table, ondelete="CASCADE"):
    return sa.ForeignKeyConstraint([col], [f"{table}.id"], ondelete=ondelete)


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="planning"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _fk("tenant_id", "companies"),
    )
    op.create_index("ix_meetings_tenant_id", "meetings", ["tenant_id"])
    op.create_index("ix_meetings_tenant_status", "meetings", ["tenant_id", "status"])

    op.create_table(
        "meeting_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key", sa.String(32), nullable=False, server_default=""),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column("role_name", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column("depends_on_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("plan_id", sa.String(36), nullable=True),
        sa.Column("pending_task_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _fk("meeting_id", "meetings"),
        _fk("tenant_id", "companies"),
    )
    op.create_index("ix_meeting_tasks_meeting_id", "meeting_tasks", ["meeting_id"])
    op.create_index("ix_meeting_tasks_tenant_id", "meeting_tasks", ["tenant_id"])

    op.create_table(
        "meeting_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sender_kind", sa.String(16), nullable=False),
        sa.Column("sender_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("recipient_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="message"),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        _fk("meeting_id", "meetings"),
        _fk("tenant_id", "companies"),
    )
    op.create_index("ix_meeting_messages_meeting_id", "meeting_messages", ["meeting_id"])
    op.create_index("ix_meeting_messages_tenant_id", "meeting_messages", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("meeting_messages")
    op.drop_table("meeting_tasks")
    op.drop_table("meetings")
