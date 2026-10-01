"""
EAAWP Email Integration ORM Models

ExternalIntegration — persists provider configuration per tenant.
EmailAuditLog       — safe audit records for every send attempt.

Security invariants
-------------------
- encrypted_password is stored using the existing Fernet encryption.
- The plain-text password is NEVER persisted or logged.
- EmailAuditLog stores only safe metadata — no credentials, no email body.
- Tenant isolation: every row has tenant_id; all queries must filter by it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ExternalIntegration(Base):
    """
    Persists an external provider integration configuration per tenant.

    One row per (tenant_id, provider_type) — currently only "smtp".
    Credentials are stored encrypted using the existing crypto module.

    Status lifecycle:
        not_configured → not_tested → connected → failed
        Any state → disabled (admin can disable without deleting config)
    """

    __tablename__ = "external_integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="smtp"
    )  # "smtp" — extensible to "sendgrid", "mailgun", etc.

    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # SMTP configuration
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Password stored encrypted — NEVER returned in API responses
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False, default="")

    tls_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="starttls"
    )  # "none" | "starttls" | "ssl_tls"

    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sender_display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Status / health
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_tested"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmailAuditLog(Base):
    """
    Safe audit record for every email send attempt.

    Security: NEVER stores SMTP password, credentials, full email body,
    or authentication tokens. Only safe metadata.
    """

    __tablename__ = "email_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Safe metadata only — no credentials, no full body
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Comma-separated domains only (e.g. "gmail.com,company.com") — no full addresses
    recipient_domains: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    subject_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Outcome
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
