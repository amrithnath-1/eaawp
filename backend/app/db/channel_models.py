"""EAAWP Marketing Channel Integration Model"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class MarketingChannelIntegration(Base):
    """
    A marketing channel integration for a tenant.
    channel_type: email_marketing | social_linkedin | social_twitter | cms | ads | custom
    status: not_configured | not_tested | connected | failed | disabled
    Credentials stored encrypted. Never returned to frontend.
    """
    __tablename__ = "marketing_channel_integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(128), nullable=False, default="mock")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_configured")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Encrypted credentials — never returned to frontend
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Safe capabilities JSON (no credentials)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    account_info_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
