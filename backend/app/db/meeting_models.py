"""
Meeting Room: a persistent, multi-agent working session.

A meeting has an objective, a set of delegated tasks (one per AI role) and a
message log of what the coordinator, the agents and the user actually said.
Nothing here is simulated: every task row is produced by a real agent execution
(same governed pipeline as the single-agent chat) and every message is stored.
Rows hold no credentials; agent output is stored because the user needs to read
it, so reads are limited to the meeting's creator and company administrators.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    # planning | queued | running | awaiting_approval | waiting_setup | completed | partial | failed | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="planning")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_meetings_tenant_status", "tenant_id", "status"),)


class MeetingTask(Base):
    """One delegated subtask, executed by one AI role."""

    __tablename__ = "meeting_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # list of task keys
    # pending | running | completed | failed | skipped | awaiting_approval | waiting_setup | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pending_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MeetingMessage(Base):
    __tablename__ = "meeting_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # user | coordinator | agent | system
    sender_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    recipient_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # message | delegation | result | status | summary
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="message")
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
