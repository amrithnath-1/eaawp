"""
Pending tasks: a user's request that could not run yet because a required
integration was not set up (credentials, authorisation or a role grant).

The row keeps the ORIGINAL request so it can be resumed after an administrator
finishes setup, without the user having to retype it.  It stores no
credentials and no tool output - only the request text and what is missing.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PendingTask(Base):
    __tablename__ = "pending_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Who asked.  The resumed run is attributed to this user.
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # waiting_setup | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting_setup")
    # What the task needs, e.g. {"provider_type": "google_analytics", "capabilities": ["run_report"]}
    requirement_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Last assessment: needs_configuration | needs_authorization | needs_grant
    blocking_state: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    resumed_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_pending_tasks_tenant_status", "tenant_id", "status"),)
