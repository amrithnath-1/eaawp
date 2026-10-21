"""
Institutional Clerk: service requests (certificates, leave, fee queries...), their timeline, and
generated documents (draft -> issued with a serial number -> optionally void).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="normal")
    requester_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    requester_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    assignee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assignee_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("ix_service_requests_tenant_status", "tenant_id", "status"),)


class ServiceRequestEvent(Base):
    __tablename__ = "service_request_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="comment")
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Internal notes are visible to administrators only (never to the requester).
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IssuedDocument(Base):
    __tablename__ = "issued_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("service_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    serial: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    issued_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "serial", name="uq_issued_documents_tenant_serial"),)
