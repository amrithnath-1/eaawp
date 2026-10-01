"""
EAAWP Email Draft ORM Model

Stores email drafts created by draft_email — internal records only.
No credentials, no SMTP state, no external side effects.

Draft lifecycle:
    draft   → created by draft_email action, pending human review
    sent    → after successful send_email action execution
    rejected → after human rejects the send_email approval
    cancelled → explicitly discarded
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class EmailDraft(Base):
    """
    Internal email draft record — no external side effects.
    Only draft_email writes to this table. send_email reads from here
    (via plan step context) but does not require it.

    Security:
    - Never stores SMTP credentials.
    - Never triggers external communication.
    - Tenant isolated via tenant_id.
    """

    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)

    # Email content
    recipients_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metadata
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Status
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft"
    )  # draft | sent | rejected | cancelled

    # Link to the approval/plan that dispatched sending
    linked_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
