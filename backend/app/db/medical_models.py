"""
Medical Assistant (clinic support): appointment requests with intake information.
Sensitive by nature: visible to the patient (own) and company administrators only; every administrator access is audited.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    patient_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    contact: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preferred_time: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    scheduled_for: Mapped[str | None] = mapped_column(String(25), nullable=True)
    clinician_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Set by the deterministic safety screen on the reason text; urgent requests sort first and carry a notice.
    red_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    red_flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    intake_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("ix_appointments_tenant_status", "tenant_id", "status"),)
