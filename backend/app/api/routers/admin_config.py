"""
EAAWP Admin-Assisted Configuration Engine — Admin Config Router.

POST /api/v1/admin/provider-config/{provider_type}
    Submit server-level configuration fields for a provider.
    Admin-only. Stores fields encrypted. Never returns values.

GET /api/v1/admin/provider-config/{provider_type}/status
    Check which fields are configured for a provider.
    Any authenticated user. Returns booleans/keys only — no values.

CRITICAL SECURITY INVARIANTS:
- POST endpoint returns only field keys, never values.
- Validation errors must not echo back secret values in messages.
- 403 enforced by require_admin for write operations.
- Tenant isolation: tenant_id comes from authenticated JWT, never request body.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant_id, require_admin
from app.db.models import User
from app.db.session import get_db
from app.integrations.integration_registry import integration_registry
from app.schemas.nl_integration import KNOWN_PROVIDERS
from app.services.provider_config_service import (
    get_provider_configuration_status,
    store_provider_field,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/provider-config",
    tags=["admin-config"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ProviderConfigSubmitRequest(BaseModel):
    """
    Fields to submit for a provider.
    dict[field_key → plaintext_value]
    Values are encrypted immediately in the service layer — never stored as plaintext.
    """
    fields: dict[str, str]


class ProviderConfigSubmitResponse(BaseModel):
    """Response after submitting config — keys only, never values."""
    status: str
    configured_fields: list[str]


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_field_value(
    provider_type: str,
    field_key: str,
    value: str,
    is_secret: bool,
) -> None:
    """
    Validate a single field value. Raises HTTPException 422 on failure.

    SECURITY: Error messages must NEVER echo back the value for secret fields.
    For non-secret fields (client_id, redirect_uri) limited information is OK.
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_key}' cannot be empty.",
        )

    if len(value) > 2048:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_key}' exceeds maximum length.",
        )

    if field_key == "redirect_uri" or (not is_secret and field_key.endswith("_uri")):
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field_key}' must be a valid http or https URL.",
            )

    # For Google client_id: soft format check (non-blocking in the service,
    # but we do validate it is a non-empty string ≤ 256 chars).
    if field_key == "client_id" and provider_type in ("google_search_console", "google_analytics"):
        if len(value) > 256:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Google Client ID must not exceed 256 characters.",
            )


# ── POST /{provider_type} — submit configuration fields (admin only) ──────────

@router.post(
    "/{provider_type}",
    response_model=ProviderConfigSubmitResponse,
    summary="Submit server-level configuration for a provider (admin only)",
    description=(
        "Store one or more configuration fields for an integration provider. "
        "Secret fields (client_secret, api_key, etc.) are encrypted immediately "
        "and never returned or logged. Returns only field keys, never values."
    ),
)
async def submit_provider_config(
    provider_type: str,
    body: ProviderConfigSubmitRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProviderConfigSubmitResponse:
    """
    Submit provider configuration fields. Admin only.

    - Validates provider_type is known.
    - Validates each field value (format, length).
    - Encrypts and stores each field.
    - Returns the list of configured field keys — never values.
    - 403 if caller is not admin (enforced by require_admin dependency).
    - 422 if any field value fails validation.
    """
    if provider_type not in KNOWN_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider type: {provider_type!r}. "
                   f"Known providers: {sorted(KNOWN_PROVIDERS)}",
        )

    if not body.fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided.",
        )

    # Build a map of field metadata to know which fields are secret.
    provider_obj = integration_registry.get(provider_type)
    secret_keys: set[str] = set()
    if provider_obj is not None:
        for req_field in provider_obj.configuration_requirements():
            if req_field.is_secret:
                secret_keys.add(req_field.key)

    # Validate all fields before storing any (fail-fast before writes).
    for field_key, value in body.fields.items():
        is_secret = field_key in secret_keys
        _validate_field_value(provider_type, field_key, value, is_secret)

    # Store each field (encrypted) and write audit logs.
    # admin_user.id is used as configured_by — never log values.
    configured_field_keys: list[str] = []
    for field_key, value in body.fields.items():
        try:
            await store_provider_field(
                provider_type=provider_type,
                field_key=field_key,
                value=value,          # encrypted immediately in service layer
                tenant_id=admin_user.tenant_id,
                configured_by=admin_user.id,
                db=db,
            )
            configured_field_keys.append(field_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    await db.commit()

    # Return only keys — NEVER values.
    return ProviderConfigSubmitResponse(
        status="ok",
        configured_fields=configured_field_keys,
    )


# ── GET /{provider_type}/status — configuration status (any authenticated user) ─

@router.get(
    "/{provider_type}/status",
    summary="Get configuration status for a provider",
    description=(
        "Returns which configuration fields are present (as booleans/keys only). "
        "Available to all authenticated users so the UI can check if config is needed. "
        "Never returns actual credential values."
    ),
)
async def get_provider_config_status(
    provider_type: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return configuration state for a provider.

    - Returns field keys and booleans, never values.
    - Any authenticated user may check status (to show configuration prompt).
    - 422 if provider_type is unknown.
    """
    if provider_type not in KNOWN_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider type: {provider_type!r}.",
        )

    config_status = await get_provider_configuration_status(
        provider_type=provider_type,
        tenant_id=tenant_id,
        db=db,
    )

    # Serialize to safe dict — only booleans, keys, and strings. NEVER values.
    return {
        "provider_type": config_status.provider_type,
        "state": config_status.state,
        "configured_fields": config_status.configured_fields,   # keys only
        "missing_fields": config_status.missing_fields,         # keys only
        "oauth_ready": config_status.oauth_ready,
        "redirect_uri": config_status.redirect_uri,             # safe metadata
        "message": config_status.message,
    }
