"""
EAAWP Dynamic Integration Framework — API Router

Prefix: /api/v1/integration-manager
All tenant endpoints require an authenticated user and derive the tenant from the JWT.

Endpoints
─────────
GET    /providers                               — catalogue of all registered providers
GET    /status                                  — framework health (no credentials)

POST   /integrations                            — create integration
GET    /integrations                            — list integrations for tenant
GET    /integrations/{id}                       — get one integration
PATCH  /integrations/{id}                       — update (rotate credentials, rename, toggle)
DELETE /integrations/{id}                       — delete

POST   /integrations/{id}/test                  — test connectivity
POST   /integrations/{id}/discover              — discover entities/schema

GET    /integrations/{id}/grants                — list capability grants
POST   /integrations/{id}/grants                — create / upsert grant
DELETE /grants/{grant_id}                       — delete a grant

POST   /integrations/{id}/execute               — execute a capability (agent-facing)

Security
────────
- encrypted_credentials is NEVER returned in any response.
- has_credentials (bool) is the only indicator of stored credentials.
- execute/ always checks capability grants before dispatching to the provider.
- All endpoints require X-Tenant-ID (consistent with rest of API).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant_id, require_admin
from app.db.models import User
from app.db.session import get_db
from app.integrations import manager as mgr
from app.integrations.integration_registry import integration_registry
from app.schemas.integration_framework import (
    CapabilityGrantBulkCreate,
    CapabilityGrantOut,
    DiscoverEntitiesResponse,
    DynamicToolInfo,
    ExecuteCapabilityRequest,
    ExecuteCapabilityResponse,
    IntegrationCreate,
    IntegrationFrameworkStatus,
    IntegrationOut,
    IntegrationTestResponse,
    IntegrationUpdate,
    ProviderCatalogueItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/integration-manager",
    tags=["integration-manager"],
)


# Tenant identity always comes from the authenticated JWT.


# ── Framework metadata ────────────────────────────────────────────────────────

@router.get(
    "/providers",
    response_model=list[ProviderCatalogueItem],
    summary="List all registered integration provider types",
    description=(
        "Returns a catalogue of every provider type the framework supports. "
        "Safe to call without credentials — no secrets returned."
    ),
)
async def list_providers() -> list[ProviderCatalogueItem]:
    """Return all registered providers as a safe catalogue."""
    return [ProviderCatalogueItem(**item) for item in integration_registry.provider_catalogue()]


@router.get(
    "/status",
    response_model=IntegrationFrameworkStatus,
    summary="Integration Framework health status",
)
async def framework_status() -> IntegrationFrameworkStatus:
    """Return a safe summary of the Integration Framework state."""
    types = integration_registry.list_types()
    return IntegrationFrameworkStatus(
        registered_provider_count=len(types),
        registered_provider_types=types,
        is_ready=len(types) > 0,
    )


# ── Integration CRUD ──────────────────────────────────────────────────────────

@router.post(
    "/integrations",
    response_model=IntegrationOut,
    status_code=201,
    summary="Create a new integration",
)
async def create_integration(
    body: IntegrationCreate,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    try:
        return await mgr.create_integration(body, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/integrations",
    response_model=list[IntegrationOut],
    summary="List integrations for the current tenant",
)
async def list_integrations(
    provider_type: str | None = None,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationOut]:
    return await mgr.list_integrations(tenant_id, db, provider_type=provider_type)


@router.get(
    "/integrations/{integration_id}",
    response_model=IntegrationOut,
    summary="Get a single integration",
)
async def get_integration(
    integration_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    try:
        return await mgr.get_integration(integration_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/integrations/{integration_id}",
    response_model=IntegrationOut,
    summary="Update an integration (rename, rotate credentials, toggle enabled)",
)
async def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    try:
        return await mgr.update_integration(integration_id, body, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/integrations/{integration_id}",
    response_model=dict,
    summary="Delete an integration and all its capability grants",
)
async def delete_integration(
    integration_id: str,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await mgr.delete_integration(integration_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Audit the disconnect
    try:
        import uuid as _uuid_mod
        from app.db.models import AuditLog
        audit = AuditLog(
            id=str(_uuid_mod.uuid4()),
            tenant_id=tenant_id,
            actor=_admin.email or _admin.id,
            event=f"integration.deleted: integration_id={integration_id}",
            department="integrations",
            status="ok",
        )
        db.add(audit)
        await db.commit()
    except Exception as audit_exc:
        logger.warning("Delete integration audit write failed (non-fatal): %s", audit_exc)

    return {"deleted": integration_id}


# ── Connection Test ───────────────────────────────────────────────────────────

@router.post(
    "/integrations/{integration_id}/test",
    response_model=IntegrationTestResponse,
    summary="Test connectivity for an integration",
    description=(
        "Decrypts credentials in-memory, calls the provider test, "
        "updates status. Credentials are never returned."
    ),
)
async def test_integration(
    integration_id: str,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationTestResponse:
    try:
        return await mgr.test_integration(integration_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Entity Discovery ──────────────────────────────────────────────────────────

@router.post(
    "/integrations/{integration_id}/discover",
    response_model=DiscoverEntitiesResponse,
    summary="Discover entities/schema for a connected integration",
    description=(
        "Requires status == 'connected'. Returns metadata only — "
        "no data rows, no credentials."
    ),
)
async def discover_entities(
    integration_id: str,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DiscoverEntitiesResponse:
    try:
        return await mgr.discover_integration_entities(integration_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── Capability Grants ─────────────────────────────────────────────────────────

@router.get(
    "/integrations/{integration_id}/grants",
    response_model=list[CapabilityGrantOut],
    summary="List capability grants for an integration",
)
async def list_grants(
    integration_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[CapabilityGrantOut]:
    try:
        grants = await mgr.list_capability_grants(integration_id, tenant_id, db)
        return [CapabilityGrantOut.model_validate(g) for g in grants]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/integrations/{integration_id}/grants",
    response_model=list[CapabilityGrantOut],
    status_code=201,
    summary="Grant capabilities to AI employee roles (bulk)",
)
async def create_grants(
    integration_id: str,
    body: CapabilityGrantBulkCreate,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[CapabilityGrantOut]:
    try:
        created = []
        for grant_body in body.grants:
            grant = await mgr.create_capability_grant(
                integration_id, grant_body, tenant_id, db
            )
            created.append(CapabilityGrantOut.model_validate(grant))
        return created
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/grants/{grant_id}",
    response_model=dict,
    summary="Delete a capability grant",
)
async def delete_grant(
    grant_id: str,
    _admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await mgr.delete_capability_grant(grant_id, tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": grant_id}


# ── Capability Execution ──────────────────────────────────────────────────────

@router.post(
    "/integrations/{integration_id}/execute",
    response_model=ExecuteCapabilityResponse,
    summary="Execute a capability on behalf of an AI employee role",
    description=(
        "Validates capability grants before executing. "
        "Returns safe results — never credentials or raw connection details."
    ),
)
async def execute_capability(
    integration_id: str,
    body: ExecuteCapabilityRequest,
    current_user: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ExecuteCapabilityResponse:
    # role_key comes from the request body but we validate it is a known role key —
    # arbitrary string injection cannot grant additional permissions because the
    # execute_capability service still checks CapabilityGrant.role_key == body.role_key
    # against the DB.  We add a format guard here as a defence-in-depth measure.
    import re
    if body.role_key and not re.match(r"^[A-Z_]{3,64}$", body.role_key):
        raise HTTPException(
            status_code=400,
            detail="role_key must be an uppercase snake_case identifier (e.g. DIGITAL_MARKETING_MANAGER).",
        )
    try:
        return await mgr.execute_capability(
            integration_id=integration_id,
            capability_key=body.capability_key,
            parameters=body.parameters,
            role_key=body.role_key,
            tenant_id=tenant_id,
            db=db,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Phase 3: Dynamic Tool Discovery ──────────────────────────────────────────

@router.get(
    "/tools",
    response_model=list[DynamicToolInfo],
    summary="List dynamic integration tools available to a role",
    description=(
        "Returns the tools currently available to the specified AI employee role "
        "for this tenant. Only shows tools where: integration is connected + enabled, "
        "capability grant exists for the role. "
        "Safe metadata only — no credentials, no connection strings."
    ),
)
async def list_available_tools(
    role_key: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[DynamicToolInfo]:
    """
    Return the dynamic tools currently available to a role for this tenant.

    Useful for:
    - Admin UI showing which integrations an AI employee can use
    - Debugging capability grant configuration
    - Pre-flight check before executing an agent

    Does NOT make any provider API calls — reads DB only.
    Never returns credentials or sensitive configuration.
    """
    from app.tools.dynamic_tool import get_available_tools

    try:
        defns = await get_available_tools(
            tenant_id=tenant_id,
            role_key=role_key,
            db=db,
        )
        return [
            DynamicToolInfo(
                tool_key=d.tool_key,
                integration_id=d.integration_id,
                integration_name=d.integration_name,
                provider_type=d.provider_type,
                capability_key=d.capability_key,
                description=d.description,
                risk_level=d.risk_level,
                is_read_only=d.is_read_only,
                is_enabled=d.is_enabled,
                input_schema=d.input_schema,
            )
            for d in defns
        ]
    except Exception as exc:
        logger.error("Tool discovery error: %s", exc)
        raise HTTPException(status_code=500, detail="Tool discovery failed.") from exc
