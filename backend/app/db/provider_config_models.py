"""
EAAWP Provider Server Configuration ORM Model.

Stores server-level (global) configuration fields for integration providers,
such as Google OAuth App credentials (client_id, client_secret, redirect_uri)
and Facebook App credentials (app_id, app_secret).

SECURITY INVARIANTS:
- encrypted_value stores Fernet-encrypted ciphertext — NEVER plaintext.
- Values are NEVER returned in API responses or placed in LLM context.
- Only AuditLog metadata (provider_type.field_key, actor) is ever logged.
- Tenant isolation: every row is scoped to a single tenant_id.
- UniqueConstraint prevents duplicate rows per (tenant, provider, field).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ProviderServerConfig(Base):
    """
    One row per configured field per provider per tenant.

    For example, a tenant that has configured Google Search Console OAuth will
    have three rows:
        (tenant_id, "google_search_console", "client_id",     <encrypted>)
        (tenant_id, "google_search_console", "client_secret", <encrypted>)
        (tenant_id, "google_search_console", "redirect_uri",  <encrypted>)

    The encrypted_value column stores the Fernet ciphertext of the plaintext
    value. Use encrypt_password / decrypt_password from app.integrations.crypto
    to read/write the value. The raw plaintext must never be stored or logged.
    """

    __tablename__ = "provider_server_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Fernet-encrypted ciphertext. NEVER return or log the decrypted value.
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    configured_by: Mapped[str] = mapped_column(String(128), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_type", "field_key",
            name="uq_provider_server_config",
        ),
    )
