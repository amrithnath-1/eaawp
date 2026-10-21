"""
EAAWP Dynamic Integration Framework — Integration Manager Service

The Integration Manager is the single service that orchestrates all
integration operations for a tenant.  It sits between the API router
and the provider implementations.

Responsibilities
────────────────
1. CRUD for Integration records (integration_catalog table)
2. Credential encryption/decryption via the existing crypto module
3. Routing test_connection / execute / discover_entities to the correct
   IntegrationProvider via the registry
4. Enforcing capability grants before any execute() call
5. Writing audit records for all capability executions (reuses DataAccessAudit)

Security invariants
───────────────────
- Credentials are decrypted in-memory only, discarded after the provider call.
- encrypted_credentials is NEVER included in return values.
- Capability execution is always gated by has_capability_grant().
- Provider type is always validated against the registry before use.
- Tenant isolation: every DB query includes a tenant_id filter.

This service is independent of FastAPI — it can be called from tests,
background tasks, or the API router.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.integration_models import CapabilityGrant, Integration
from app.integrations.crypto import decrypt_password, encrypt_password
from app.integrations.integration_registry import integration_registry
from app.schemas.integration_framework import (
    CapabilityGrantCreate,
    DiscoverEntitiesResponse,
    DiscoveredEntityOut,
    ExecuteCapabilityResponse,
    IntegrationCreate,
    IntegrationOut,
    IntegrationTestResponse,
    IntegrationUpdate,
)

logger = logging.getLogger(__name__)


# ── Credential helpers ────────────────────────────────────────────────────────

def _encrypt_credentials(credentials: dict[str, Any]) -> str:
    """Serialise credentials dict to JSON then Fernet-encrypt the string."""
    raw_json = json.dumps(credentials)
    return encrypt_password(raw_json)


def _decrypt_credentials(encrypted: str) -> dict[str, Any]:
    """Decrypt and deserialise credentials from an encrypted blob."""
    raw_json = decrypt_password(encrypted)
    return json.loads(raw_json)


# ── ORM → schema conversion ───────────────────────────────────────────────────

def _integration_to_out(row: Integration) -> IntegrationOut:
    """Convert an Integration ORM row to the public-safe IntegrationOut schema."""
    account_info: dict[str, Any] = {}
    try:
        account_info = json.loads(row.account_info_json or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    return IntegrationOut(
        id=row.id,
        tenant_id=row.tenant_id,
        provider_type=row.provider_type,
        display_name=row.display_name,
        status=row.status,  # type: ignore[arg-type]
        is_enabled=row.is_enabled,
        has_credentials=bool(row.encrypted_credentials),
        account_info=account_info,
        last_tested_at=row.last_tested_at,
        error_message=row.error_message,
        legacy_connection_id=row.legacy_connection_id,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── Disconnect: revoke the OAuth grant at the provider ────────────────────────

_GOOGLE_OAUTH_PROVIDERS = {"google_search_console", "google_analytics"}
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


async def _revoke_google_token(encrypted: str) -> bool:
    """Best-effort revocation so "disconnect" really ends Google's access.

    Revoking the refresh token also invalidates the access tokens derived from
    it.  Failures (offline, already revoked) never block the local delete, and
    nothing about the token or the response body is logged.
    """
    import asyncio

    try:
        creds = _decrypt_credentials(encrypted)
        token = creds.get("refresh_token") or creds.get("access_token")
        creds.clear()
        if not token:
            return False

        def _post() -> int:
            import requests

            return requests.post(
                _GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5,
            ).status_code

        status = await asyncio.get_running_loop().run_in_executor(None, _post)
        ok = status == 200
        logger.info("Google token revocation on disconnect: %s", "ok" if ok else f"http {status}")
        return ok
    except Exception as exc:  # network down, bad blob, ... — never block disconnect
        logger.warning("Google token revocation failed (%s); credentials are still deleted locally", type(exc).__name__)
        return False


# ── Helper: fetch integration or raise ───────────────────────────────────────

async def _get_integration_or_raise(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Integration:
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise LookupError(
            f"Integration '{integration_id}' not found for tenant '{tenant_id}'."
        )
    return row


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def create_integration(
    body: IntegrationCreate,
    tenant_id: str,
    db: AsyncSession,
) -> IntegrationOut:
    """
    Create a new Integration record.

    Validates the provider type against the registry.
    Encrypts credentials before persisting.
    Status starts at 'not_tested'.
    """
    # Validate provider type
    if not integration_registry.has(body.provider_type):
        available = integration_registry.list_types()
        raise ValueError(
            f"Unknown provider type '{body.provider_type}'. "
            f"Available: {available}"
        )

    if body.provider_type == "mcp":
        from app.integrations.providers.mcp_provider import MCPError, validate_mcp_credentials
        try:
            validate_mcp_credentials(body.credentials)
        except MCPError as exc:
            raise ValueError(str(exc)) from exc

    encrypted = _encrypt_credentials(body.credentials)

    row = Integration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider_type=body.provider_type,
        display_name=body.display_name,
        encrypted_credentials=encrypted,
        status="not_tested",
        is_enabled=False,
        account_info_json="{}",
        created_by=body.created_by,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "Integration created: tenant=%s provider=%s id=%s",
        tenant_id, body.provider_type, row.id,
    )
    return _integration_to_out(row)


async def list_integrations(
    tenant_id: str,
    db: AsyncSession,
    provider_type: str | None = None,
) -> list[IntegrationOut]:
    """List all integrations for a tenant, optionally filtered by provider type."""
    query = select(Integration).where(Integration.tenant_id == tenant_id)
    if provider_type:
        query = query.where(Integration.provider_type == provider_type)
    query = query.order_by(Integration.created_at.desc())
    result = await db.execute(query)
    return [_integration_to_out(row) for row in result.scalars().all()]


async def get_integration(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> IntegrationOut:
    """Fetch a single integration by ID."""
    row = await _get_integration_or_raise(integration_id, tenant_id, db)
    return _integration_to_out(row)


async def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    tenant_id: str,
    db: AsyncSession,
) -> IntegrationOut:
    """Partial update. Rotating credentials resets status to not_tested."""
    row = await _get_integration_or_raise(integration_id, tenant_id, db)

    if body.display_name is not None:
        row.display_name = body.display_name
    if body.credentials is not None:
        if row.provider_type == "mcp":
            from app.integrations.providers.mcp_provider import MCPError, validate_mcp_credentials
            try:
                validate_mcp_credentials(body.credentials)
            except MCPError as exc:
                raise ValueError(str(exc)) from exc
            try:
                _old_url = str(_decrypt_credentials(row.encrypted_credentials).get("server_url", "")).rstrip("/")
            except Exception:  # noqa: BLE001
                _old_url = ""
            if _old_url != str(body.credentials.get("server_url", "")).rstrip("/"):
                # A different server exposes different tools: per-tool grants made for the old one must be re-reviewed.
                await db.execute(delete(CapabilityGrant).where(
                    CapabilityGrant.integration_id == integration_id, CapabilityGrant.tenant_id == tenant_id,
                    CapabilityGrant.capability_key.like(f"{MCP_TOOL_PREFIX}%")))
        row.encrypted_credentials = _encrypt_credentials(body.credentials)
        row.status = "not_tested"   # force re-test after credential rotation
        row.error_message = None
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled

    await db.flush()
    # ``updated_at`` is a server-side onupdate column: flush expires it, and
    # reading it lazily in async mode raises MissingGreenlet.  This crashed the
    # OAuth callback (token storage) and PATCH /integrations/{id}.
    await db.refresh(row)
    return _integration_to_out(row)


async def delete_integration(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """Delete an integration and all its capability grants (CASCADE)."""
    row = await _get_integration_or_raise(integration_id, tenant_id, db)
    if row.encrypted_credentials and row.provider_type in _GOOGLE_OAUTH_PROVIDERS:
        await _revoke_google_token(row.encrypted_credentials)
    # Remove the grants explicitly: SQLite does not enforce ON DELETE CASCADE
    # unless PRAGMA foreign_keys is on, which would leave orphaned grants.
    await db.execute(
        delete(CapabilityGrant).where(
            CapabilityGrant.integration_id == integration_id,
            CapabilityGrant.tenant_id == tenant_id,
        )
    )
    await db.delete(row)
    await db.flush()
    logger.info("Integration deleted: tenant=%s id=%s", tenant_id, integration_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Connection Test
# ═══════════════════════════════════════════════════════════════════════════════

def default_property_of(row: Integration) -> str:
    """The property an administrator selected for this connection ('' if none)."""
    try:
        value = json.loads(row.account_info_json or "{}").get("default_property", "")
    except (ValueError, AttributeError, TypeError):
        return ""
    return value if isinstance(value, str) else ""


async def list_selectable_properties(
    integration_id: str, tenant_id: str, db: AsyncSession
) -> list[dict[str, str]]:
    """
    Fresh list of properties the connected account can read, for an admin to
    choose from.  Raises ValueError with a safe message when it cannot be listed.
    """
    row = await _get_integration_or_raise(integration_id, tenant_id, db)
    provider = integration_registry.get_or_raise(row.provider_type)
    if not getattr(provider, "property_parameter", None):
        return []
    if row.status != "connected" or not row.is_enabled or not row.encrypted_credentials:
        raise ValueError("The integration is not connected.")
    credentials: dict[str, Any] = {}
    try:
        credentials = _decrypt_credentials(row.encrypted_credentials)
        before = credentials.get("access_token"), credentials.get("token_expiry")
        try:
            props = await provider.list_properties(credentials)
        except Exception as exc:
            raise ValueError(provider._sanitise_error(str(exc))) from None
        after = credentials.get("access_token"), credentials.get("token_expiry")
        if after != before and credentials.get("access_token"):
            row.encrypted_credentials = _encrypt_credentials(credentials)
            await db.flush()
        return props
    finally:
        credentials.clear()


async def set_default_property(
    integration_id: str, tenant_id: str, property_id: str, db: AsyncSession
) -> str:
    """Store the admin's choice - only if the account can really read that property."""
    props = await list_selectable_properties(integration_id, tenant_id, db)
    if property_id not in {p["id"] for p in props}:
        raise ValueError("That property is not one of the properties this Google account can access.")
    row = await _get_integration_or_raise(integration_id, tenant_id, db)
    try:
        info = json.loads(row.account_info_json or "{}")
    except ValueError:
        info = {}
    info["default_property"] = property_id
    row.account_info_json = json.dumps(info)
    await db.flush()
    return property_id


async def test_integration(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> IntegrationTestResponse:
    """
    Test the connection for an integration.

    Decrypts credentials in-memory, calls provider.test_connection(),
    updates the status and account_info, then discards credentials.
    """
    row = await _get_integration_or_raise(integration_id, tenant_id, db)

    if not row.encrypted_credentials:
        row.status = "not_configured"
        await db.flush()
        now = datetime.now(timezone.utc)
        return IntegrationTestResponse(
            integration_id=integration_id,
            provider_type=row.provider_type,
            success=False,
            status="not_configured",  # type: ignore[arg-type]
            account_info={},
            error_message="No credentials configured. Update the integration with credentials first.",
            tested_at=now,
        )

    provider = integration_registry.get_or_raise(row.provider_type)

    credentials: dict[str, Any] = {}
    try:
        credentials = _decrypt_credentials(row.encrypted_credentials)
        result = await provider.test_connection(credentials)
    except Exception as exc:
        logger.error(
            "Integration test error: id=%s provider=%s error=%s",
            integration_id, row.provider_type, provider._sanitise_error(str(exc)),
        )
        result_success = False
        result_account_info: dict = {}
        result_error = provider._sanitise_error(str(exc))
    else:
        result_success = result.success
        result_account_info = result.account_info
        result_error = result.error_message
    finally:
        # Explicitly discard decrypted credentials from local scope
        credentials.clear()

    now = datetime.now(timezone.utc)
    row.status = "connected" if result_success else "failed"
    row.last_tested_at = now
    row.error_message = result_error
    if result_success:
        previous_default = default_property_of(row)
        row.account_info_json = json.dumps(
            {**result_account_info, **({"default_property": previous_default} if previous_default else {})}
        )
        row.is_enabled = True   # auto-enable on first successful test
    await db.flush()

    return IntegrationTestResponse(
        integration_id=integration_id,
        provider_type=row.provider_type,
        success=result_success,
        status=row.status,  # type: ignore[arg-type]
        account_info=result_account_info,
        error_message=result_error,
        tested_at=now,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Entity / Schema Discovery
# ═══════════════════════════════════════════════════════════════════════════════

async def discover_integration_entities(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> DiscoverEntitiesResponse:
    """
    Discover entities (tables/views/datasets) for an integration.

    Requires status == 'connected'.
    Decrypts credentials, calls provider.discover_entities(), discards credentials.
    Does NOT persist entities to schema_entities — that table belongs to the
    legacy DataConnection subsystem.  The Integration Framework returns the
    raw discovery result; callers can persist as needed.
    """
    row = await _get_integration_or_raise(integration_id, tenant_id, db)

    if row.status != "connected":
        raise ValueError(
            f"Integration '{integration_id}' is not connected (status: {row.status}). "
            "Test the connection first."
        )

    provider = integration_registry.get_or_raise(row.provider_type)

    credentials: dict[str, Any] = {}
    entities: list[dict[str, Any]] = []
    try:
        credentials = _decrypt_credentials(row.encrypted_credentials)
        entities = await provider.discover_entities(credentials)
    except Exception as exc:
        logger.error(
            "Entity discovery error: id=%s error=%s", integration_id, exc
        )
        raise RuntimeError(
            f"Entity discovery failed: {provider._sanitise_error(str(exc))}"
        ) from exc
    finally:
        credentials.clear()

    entity_outs = [
        DiscoveredEntityOut(
            schema_name=e.get("schema_name", "default"),
            entity_name=e.get("entity_name", ""),
            entity_type=e.get("entity_type", "table"),
            column_count=e.get("column_count", len(e.get("columns", []))),
            row_count_estimate=e.get("row_count_estimate"),
            columns=e.get("columns", []),
            description=str(e.get("description", "") or "")[:500],
            risk_level=(str(e["risk_level"]) if e.get("risk_level") else None),
        )
        for e in entities
    ]

    return DiscoverEntitiesResponse(
        integration_id=integration_id,
        provider_type=row.provider_type,
        entity_count=len(entity_outs),
        entities=entity_outs,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Grants
# ═══════════════════════════════════════════════════════════════════════════════

async def list_capability_grants(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[CapabilityGrant]:
    """List all capability grants for an integration."""
    await _get_integration_or_raise(integration_id, tenant_id, db)
    result = await db.execute(
        select(CapabilityGrant).where(
            CapabilityGrant.integration_id == integration_id,
            CapabilityGrant.tenant_id == tenant_id,
        ).order_by(CapabilityGrant.role_key, CapabilityGrant.capability_key)
    )
    return list(result.scalars().all())


MCP_TOOL_PREFIX = "mcp_tool:"


async def create_capability_grant(
    integration_id: str,
    body: CapabilityGrantCreate,
    tenant_id: str,
    db: AsyncSession,
) -> CapabilityGrant:
    """
    Grant or update a capability permission.

    Validates:
    - integration exists and belongs to tenant
    - capability_key exists in the provider's declared capabilities
    Upserts: if a grant already exists for this (integration, role, capability),
    update is_granted; otherwise create a new row.
    """
    row = await _get_integration_or_raise(integration_id, tenant_id, db)

    # Validate capability_key exists in the provider
    provider = integration_registry.get_or_raise(row.provider_type)
    if row.provider_type == "mcp" and body.capability_key.startswith(MCP_TOOL_PREFIX):
        import re as _re
        if not _re.match(r"^[A-Za-z0-9_.:-]{1,110}$", body.capability_key[len(MCP_TOOL_PREFIX):]):
            raise ValueError("Invalid MCP tool name.")
    elif provider.get_capability(body.capability_key) is None:
        valid_keys = [c.key for c in provider.get_capabilities()]
        raise ValueError(
            f"Capability '{body.capability_key}' does not exist for provider "
            f"'{row.provider_type}'. Valid keys: {valid_keys}"
        )

    # Upsert
    existing_result = await db.execute(
        select(CapabilityGrant).where(
            CapabilityGrant.integration_id == integration_id,
            CapabilityGrant.role_key == body.role_key,
            CapabilityGrant.capability_key == body.capability_key,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.is_granted = body.is_granted
        existing.granted_by = body.granted_by
        existing.granted_at = datetime.now(timezone.utc)
        await db.flush()
        return existing

    grant = CapabilityGrant(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        integration_id=integration_id,
        role_key=body.role_key,
        capability_key=body.capability_key,
        is_granted=body.is_granted,
        granted_by=body.granted_by,
    )
    db.add(grant)
    await db.flush()
    return grant


async def delete_capability_grant(
    grant_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """Delete a capability grant."""
    result = await db.execute(
        select(CapabilityGrant).where(
            CapabilityGrant.id == grant_id,
            CapabilityGrant.tenant_id == tenant_id,
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise LookupError(f"Capability grant '{grant_id}' not found.")
    await db.delete(grant)
    await db.flush()


async def has_capability_grant(
    integration_id: str,
    role_key: str,
    capability_key: str,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """
    Check whether a role has an active grant for a specific capability.
    The Integration Manager calls this before any execute() call.
    """
    result = await db.execute(
        select(CapabilityGrant).where(
            CapabilityGrant.integration_id == integration_id,
            CapabilityGrant.role_key == role_key,
            CapabilityGrant.capability_key == capability_key,
            CapabilityGrant.tenant_id == tenant_id,
            CapabilityGrant.is_granted == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none() is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Execution
# ═══════════════════════════════════════════════════════════════════════════════

async def execute_capability(
    integration_id: str,
    capability_key: str,
    parameters: dict[str, Any],
    role_key: str,
    tenant_id: str,
    db: AsyncSession,
) -> ExecuteCapabilityResponse:
    """
    Execute a capability on behalf of an AI employee role.

    Security flow:
    1. Verify integration exists and belongs to tenant.
    2. Verify integration is connected and enabled.
    3. Check capability grant: role_key must have is_granted=True for this capability.
    4. Decrypt credentials (in-memory only).
    5. Delegate to provider.execute().
    6. Discard credentials immediately.
    7. Return safe result (no credentials in response).

    Raises:
        LookupError:    integration not found
        PermissionError: capability not granted to this role
        ValueError:     integration not connected / enabled, or bad parameters
    """
    row = await _get_integration_or_raise(integration_id, tenant_id, db)

    # Guard: integration must be connected and enabled
    if row.status != "connected":
        raise ValueError(
            f"Integration '{row.display_name}' is not connected "
            f"(status: {row.status}). Test the connection first."
        )
    if not row.is_enabled:
        raise PermissionError(
            f"Integration '{row.display_name}' is disabled. "
            "Enable it before executing capabilities."
        )

    # Guard: capability grant check
    granted = await has_capability_grant(
        integration_id=integration_id,
        role_key=role_key,
        capability_key=capability_key,
        tenant_id=tenant_id,
        db=db,
    )
    if not granted:
        raise PermissionError(
            f"Role '{role_key}' does not have permission to execute "
            f"capability '{capability_key}' on integration '{row.display_name}'. "
            "An administrator must grant this capability first."
        )

    # MCP: the generic call_tool grant is not enough. The specific tool must ALSO be granted to the role, so
    # connecting a server (or granting call_tool) never exposes tools nobody reviewed.
    if row.provider_type == "mcp" and capability_key == "call_tool":
        _tool = str(parameters.get("tool_name", ""))
        if not _tool or not await has_capability_grant(
            integration_id=integration_id, role_key=role_key, capability_key=f"{MCP_TOOL_PREFIX}{_tool}",
            tenant_id=tenant_id, db=db,
        ):
            raise PermissionError(
                f"Role '{role_key}' has not been granted the tool '{_tool[:80]}' on '{row.display_name}'. "
                "An administrator must grant each tool separately."
            )

    provider = integration_registry.get_or_raise(row.provider_type)

    # The company's selected property fills in when the caller did not name one.
    prop_param = getattr(provider, "property_parameter", None)
    if prop_param and not parameters.get(prop_param):
        chosen = default_property_of(row)
        if chosen:
            parameters = {**parameters, prop_param: chosen}

    credentials: dict[str, Any] = {}
    try:
        credentials = _decrypt_credentials(row.encrypted_credentials)
        # Take a snapshot of the tokens before execution so we can detect refresh
        _token_before = credentials.get("access_token"), credentials.get("token_expiry")

        result = await provider.execute(
            capability_key=capability_key,
            credentials=credentials,
            parameters=parameters,
        )

        # If the provider refreshed the access token (GSC/GA mutate the dict
        # in place), re-encrypt and persist the updated credentials immediately
        # so the next call reuses the fresh token rather than re-refreshing.
        _token_after = credentials.get("access_token"), credentials.get("token_expiry")
        if _token_after != _token_before and credentials.get("access_token"):
            try:
                row.encrypted_credentials = _encrypt_credentials(credentials)
                await db.flush()
                logger.debug(
                    "Persisted refreshed OAuth token for integration %s", integration_id
                )
            except Exception as _persist_exc:
                logger.warning(
                    "Failed to persist refreshed token for integration %s (non-fatal): %s",
                    integration_id, _persist_exc,
                )
    except (ValueError, NotImplementedError) as exc:
        return ExecuteCapabilityResponse(
            integration_id=integration_id,
            capability_key=capability_key,
            success=False,
            data={},
            row_count=0,
            truncated=False,
            source_label="",
            error=str(exc),
        )
    except Exception as exc:
        logger.error(
            "Capability execution error: integration=%s capability=%s error=%s",
            integration_id, capability_key, provider._sanitise_error(str(exc)),
        )
        return ExecuteCapabilityResponse(
            integration_id=integration_id,
            capability_key=capability_key,
            success=False,
            data={},
            row_count=0,
            truncated=False,
            source_label="",
            error=provider._sanitise_error(str(exc)),
        )
    finally:
        credentials.clear()

    return ExecuteCapabilityResponse(
        integration_id=integration_id,
        capability_key=capability_key,
        success=result.success,
        data=result.data,
        row_count=result.row_count,
        truncated=result.truncated,
        source_label=result.source_label,
        error=result.error,
    )
