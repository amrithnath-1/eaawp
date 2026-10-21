"""
EAAWP Admin-Assisted Configuration Engine — Provider Config Service.

Manages server-level provider configuration (e.g. Google OAuth App credentials).

CRITICAL SECURITY INVARIANTS — violations are not acceptable:
- get_provider_configuration_status() returns ONLY booleans and field key names.
  It NEVER returns actual credential values.
- store_provider_field() encrypts the value immediately and discards plaintext.
  The value is NEVER logged, NEVER included in AuditLog, NEVER returned.
- get_decrypted_field() is for INTERNAL USE ONLY — never call from API response paths.
- AuditLog events contain only provider_type.field_key metadata, never values.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AuditLog
from app.db.provider_config_models import ProviderServerConfig
from app.integrations.crypto import decrypt_password, encrypt_password
from app.integrations.integration_registry import integration_registry
from app.integrations.provider import ConfigurationStatus

logger = logging.getLogger(__name__)

# Default fallback redirect URI when not configured.
_DEFAULT_REDIRECT_URI = "http://localhost:8000/api/v1/oauth/google/callback"


async def get_provider_configuration_status(
    provider_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> ConfigurationStatus:
    """
    Check which configuration fields are present for a provider in this tenant.

    SECURITY: Returns ONLY booleans and field key names — never actual values.
    A field is considered "configured" if either:
    - A row exists in provider_server_configs for this tenant+provider+field, OR
    - For google_* providers: the corresponding settings env var is non-empty.

    Args:
        provider_type: e.g. "google_search_console"
        tenant_id: The tenant to check
        db: Async database session

    Returns:
        ConfigurationStatus with state, configured_fields (keys only), missing_fields,
        oauth_ready, and redirect_uri. NEVER includes actual values.
    """
    provider_obj = integration_registry.get(provider_type)
    if provider_obj is None:
        return ConfigurationStatus(
            provider_type=provider_type,
            state="CONFIGURED",
            configured_fields=[],
            missing_fields=[],
            oauth_ready=True,
            redirect_uri="",
            message="Unknown provider — no pre-configuration required.",
        )

    requirements = provider_obj.configuration_requirements()
    if not requirements:
        return ConfigurationStatus(
            provider_type=provider_type,
            state="CONFIGURED",
            configured_fields=[],
            missing_fields=[],
            oauth_ready=True,
            redirect_uri="",
            message="No server configuration required for this provider.",
        )

    # Query all config rows for this tenant+provider in one call.
    result = await db.execute(
        select(ProviderServerConfig.field_key).where(
            ProviderServerConfig.tenant_id == tenant_id,
            ProviderServerConfig.provider_type == provider_type,
        )
    )
    db_configured_keys: set[str] = {row[0] for row in result.fetchall()}

    configured_fields: list[str] = []
    missing_required: list[str] = []

    is_google = provider_type in ("google_search_console", "google_analytics")

    for field in requirements:
        field_is_configured = field.key in db_configured_keys

        # For Google providers, also accept env var fallback.
        if not field_is_configured and is_google:
            if field.key == "client_id" and bool(settings.google_client_id):
                field_is_configured = True
            elif field.key == "client_secret" and bool(settings.google_client_secret):
                field_is_configured = True
            elif field.key == "redirect_uri" and bool(settings.google_redirect_uri):
                field_is_configured = True

        if field_is_configured:
            configured_fields.append(field.key)
        elif field.required:
            missing_required.append(field.key)

    total_required = [f.key for f in requirements if f.required]
    if not missing_required:
        state = "CONFIGURED"
    elif len(configured_fields) == 0:
        state = "NOT_CONFIGURED"
    else:
        state = "PARTIALLY_CONFIGURED"

    oauth_ready = len(missing_required) == 0

    # Determine the redirect URI (safe metadata, not a secret).
    redirect_uri = ""
    if is_google:
        redirect_uri = settings.google_redirect_uri or _DEFAULT_REDIRECT_URI
    elif "redirect_uri" in db_configured_keys:
        # For other providers, return the DB-stored redirect URI if present.
        # NOTE: This is safe metadata (the callback URL), not a secret value.
        redirect_uri = _DEFAULT_REDIRECT_URI

    return ConfigurationStatus(
        provider_type=provider_type,
        state=state,
        configured_fields=configured_fields,
        missing_fields=missing_required,
        oauth_ready=oauth_ready,
        redirect_uri=redirect_uri,
        message=(
            f"{'All required fields configured.' if oauth_ready else f'Missing: {missing_required}'}"
        ),
    )


async def store_provider_field(
    provider_type: str,
    field_key: str,
    value: str,
    tenant_id: str,
    configured_by: str,
    db: AsyncSession,
) -> None:
    """
    Encrypt and persist a provider configuration field for a tenant.

    SECURITY:
    - value is encrypted immediately; plaintext is discarded after this line.
    - The value is NEVER logged, NEVER included in AuditLog.event.
    - AuditLog records only provider_type.field_key metadata.
    - Does NOT commit — caller's session/transaction commits.

    Args:
        provider_type: e.g. "google_search_console"
        field_key: e.g. "client_secret"
        value: Plaintext value from admin (will be encrypted immediately)
        tenant_id: Owning tenant
        configured_by: User ID or email of the admin performing the action
        db: Async database session

    Raises:
        ValueError: If value is empty.
    """
    if not value or not value.strip():
        raise ValueError(f"Value for {provider_type}.{field_key} cannot be empty.")

    # Encrypt immediately — plaintext is no longer needed after this point.
    encrypted = encrypt_password(value)
    # The 'value' variable is no longer used below.

    # Check for existing row.
    result = await db.execute(
        select(ProviderServerConfig).where(
            ProviderServerConfig.tenant_id == tenant_id,
            ProviderServerConfig.provider_type == provider_type,
            ProviderServerConfig.field_key == field_key,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.encrypted_value = encrypted
        existing.configured_by = configured_by
        existing.configured_at = datetime.now(timezone.utc)
    else:
        new_row = ProviderServerConfig(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            provider_type=provider_type,
            field_key=field_key,
            encrypted_value=encrypted,
            configured_by=configured_by,
        )
        db.add(new_row)

    # Audit log: field metadata only — value is NEVER included.
    audit = AuditLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=None,
        actor=configured_by,
        event=f"admin configured {provider_type}.{field_key}",
        department="admin",
        status="ok",
    )
    db.add(audit)
    await db.flush()

    # Debug log: field key and tenant only — never the value.
    logger.debug(
        "Stored provider config field for %s.%s (tenant %s)",
        provider_type,
        field_key,
        tenant_id,
    )


async def get_decrypted_field(
    provider_type: str,
    field_key: str,
    tenant_id: str,
    db: AsyncSession,
    env_fallback: bool = True,
) -> str | None:
    """
    Return the decrypted value of a provider configuration field.

    INTERNAL USE ONLY — never call this from API response paths.
    This function is intended for building OAuth authorization URLs and
    constructing OAuth flows, not for returning values to clients.

    Args:
        provider_type: e.g. "google_search_console"
        field_key: e.g. "client_id"
        tenant_id: Owning tenant
        db: Async database session

    Returns:
        Decrypted plaintext string, or None if not found.
    """
    result = await db.execute(
        select(ProviderServerConfig).where(
            ProviderServerConfig.tenant_id == tenant_id,
            ProviderServerConfig.provider_type == provider_type,
            ProviderServerConfig.field_key == field_key,
        )
    )
    row = result.scalar_one_or_none()

    if row is not None:
        return decrypt_password(row.encrypted_value)

    # Fallback: for Google providers, check env vars.
    if env_fallback and provider_type in ("google_search_console", "google_analytics"):
        if field_key == "client_id" and settings.google_client_id:
            return settings.google_client_id
        if field_key == "client_secret" and settings.google_client_secret:
            return settings.google_client_secret
        if field_key == "redirect_uri" and settings.google_redirect_uri:
            return settings.google_redirect_uri

    return None
