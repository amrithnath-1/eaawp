"""EAAWP Notification Models"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Notification(Base):
    """
    Tenant-scoped notification.
    Severity: info | warning | critical
    Category: approval | action_completed | action_failed | monitoring_alert
              | workflow | campaign | objective | agent_decision
    """
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="agent_decision")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional link to related entity
    related_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    related_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
