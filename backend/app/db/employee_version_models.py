"""
AI employee configuration versions (Phase F).

Every change to an employee's configuration is a row: v1 at approval, then one row per
natural-language revision (proposed -> approved/rejected) or rollback. Only one version is
``current``; its snapshot is what the role configuration (what the agent really runs with) was
last synced from. History is never rewritten: a rollback creates a NEW version that copies an
old snapshot. Snapshots hold configuration only - never credentials.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class EmployeeVersion(Base):
    __tablename__ = "employee_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # proposed | current | superseded | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("ai_employee_id", "version", name="uq_employee_version"),
        Index("ix_employee_versions_tenant_employee", "tenant_id", "ai_employee_id"),
    )
