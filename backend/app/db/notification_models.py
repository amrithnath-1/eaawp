"""EAAWP Notification Models"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    # Addressee. One row per recipient. NULL = a legacy company-wide row from before per-user delivery (administrators only).
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Email outbox: none | pending | sent | failed | skipped. Only ever 'pending' when the company AND the recipient consented.
    email_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none", server_default="none")
    email_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Optional link to related entity
    related_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    related_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class NotificationSettings(Base):
    """Company-level authorization for automatic notification emails. No row = NOT authorized (default off)."""
    __tablename__ = "notification_settings"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationPreference(Base):
    """One person's choice per category. No row = in-app ON, email OFF (explicit opt-in)."""
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "category", name="uq_notification_pref"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
