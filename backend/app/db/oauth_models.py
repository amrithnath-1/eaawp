"""
EAAWP OAuth 2.0 State Management — ORM Model

OAuthState
──────────
Short-lived CSRF state record binding an OAuth2 authorization request to a
specific (tenant_id, integration_id, provider) context.

Security design
───────────────
The OAuth2 "state" parameter is an opaque random token (32 bytes, hex).
This table records:
  - What tenant/integration initiated the flow
  - When it expires (10-minute TTL)
  - Whether it has already been consumed (one-time-use)

On callback:
  1. Look up state_token in this table (indexed).
  2. Verify it is not expired.
  3. Verify it has not been consumed (used = False).
  4. Extract tenant_id and integration_id — SERVER-SIDE only.
  5. Mark consumed (used = True).
  6. Exchange auth code for tokens via provider.
  7. Store encrypted tokens in integration_catalog.encrypted_credentials.

This prevents:
  • CSRF attacks     — attacker cannot forge a state they don't control
  • Replay attacks   — state is one-time-use
  • Tenant hijacking — tenant_id comes from this record, not the browser

Fields that must NEVER be stored here:
  authorization_code, access_token, refresh_token
  Those go to integration_catalog.encrypted_credentials (Fernet-encrypted)
  after a successful callback exchange.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class OAuthState(Base):
    """
    Short-lived, one-time-use CSRF state record for an in-progress OAuth2 flow.

    Created: when admin clicks "Connect" and browser is redirected to Google.
    Consumed: once Google redirects back to /api/v1/oauth/google/callback.
    Cleaned up: by a periodic task or on next access attempt after expiry.
    """

    __tablename__ = "oauth_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Opaque random token sent as the OAuth2 'state' parameter.
    # 32 bytes of os.urandom → hex string = 64 chars.  Cryptographically random.
    state_token: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )

    # Which tenant initiated the OAuth flow.
    # Derived server-side from the authenticated admin request header.
    # NEVER sourced from browser/callback parameters.
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # The integration_catalog row this flow will populate on success.
    # Created (status="not_configured") before the redirect and referenced here.
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integration_catalog.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Provider type — additional binding so callback can validate it came back
    # from the expected provider (e.g. "google_search_console").
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # UTC timestamp after which this state is considered expired and must be rejected.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # True once the callback has successfully consumed this state.
    # Subsequent attempts with the same state_token are rejected.
    used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
