"""
EAAWP Data Access Router

POST /api/v1/data/query                      — controlled structured query
GET  /api/v1/data/mappings                   — list semantic mappings
POST /api/v1/data/mappings                   — create mapping
PATCH /api/v1/data/mappings/{mapping_id}     — update mapping
DELETE /api/v1/data/mappings/{mapping_id}    — delete mapping
GET  /api/v1/data/audits                     — list data access audit records

All endpoints require X-Tenant-ID header.
No raw SQL is ever accepted or returned.
Credentials never appear in responses.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from app.core.auth import get_current_tenant_id
from app.schemas.role_config import IMPLEMENTED_ROLES
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataAccessAudit, SchemaEntity, SemanticMapping
from app.db.session import get_db
from app.schemas.data_access import (
    CompanyDataQueryRequest,
    CompanyDataQueryResponse,
    SemanticMappingCreate,
    SemanticMappingOut,
    SemanticMappingUpdate,
)
from app.services.data_access import execute_company_data_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data-access"])



# ── Controlled query ──────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=CompanyDataQueryResponse,
    summary="Execute a controlled read-only structured query against authorized company data",
)
async def query_company_data(
    body: CompanyDataQueryRequest,
    role_key: str = Header(default="DIGITAL_MARKETING_MANAGER", alias="X-Role-Key"),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CompanyDataQueryResponse:
    """
    The agent sends structured query parameters; the backend builds and
    executes a safe read-only SQL query. Raw SQL is never accepted.

    ``X-Role-Key`` is only an audit label and must name an implemented role;
    it never widens access (entity permissions are tenant-level).

    Returns 403 if the entity is not authorized.
    Returns 422 if fields/filters are invalid.
    Returns 503 if the external database is unreachable.
    """
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(status_code=400, detail="Unknown role key.")
    try:
        return await execute_company_data_query(
            request=body,
            tenant_id=tenant_id,
            role_key=role_key,
            db=db,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Data query failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Company data query failed. Check the connection and try again.",
        ) from exc


# ── Semantic mappings ─────────────────────────────────────────────────────────

@router.get("/mappings", response_model=list[SemanticMappingOut])
async def list_mappings(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SemanticMappingOut]:
    result = await db.execute(
        select(SemanticMapping)
        .where(SemanticMapping.tenant_id == tenant_id)
        .order_by(SemanticMapping.semantic_concept, SemanticMapping.field_name)
    )
    mappings = result.scalars().all()
    return [_mapping_to_schema(m) for m in mappings]


@router.post("/mappings", response_model=SemanticMappingOut, status_code=201)
async def create_mapping(
    body: SemanticMappingCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SemanticMappingOut:
    # Verify entity belongs to this tenant
    entity_result = await db.execute(
        select(SchemaEntity).where(
            SchemaEntity.id == body.entity_id,
            SchemaEntity.tenant_id == tenant_id,
        )
    )
    entity = entity_result.scalar_one_or_none()
    if not entity:
        raise HTTPException(
            status_code=404,
            detail="Entity not found or does not belong to this tenant."
        )

    mapping = SemanticMapping(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        semantic_concept=body.semantic_concept,
        connection_id=body.connection_id,
        entity_id=body.entity_id,
        field_name=body.field_name,
        display_label=body.display_label,
        created_by=body.created_by,
    )
    db.add(mapping)
    await db.flush()
    return _mapping_to_schema(mapping)


@router.patch("/mappings/{mapping_id}", response_model=SemanticMappingOut)
async def update_mapping(
    mapping_id: str,
    body: SemanticMappingUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SemanticMappingOut:
    result = await db.execute(
        select(SemanticMapping).where(
            SemanticMapping.id == mapping_id,
            SemanticMapping.tenant_id == tenant_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    if body.display_label is not None:
        mapping.display_label = body.display_label
    if body.field_name is not None:
        mapping.field_name = body.field_name
    await db.flush()
    return _mapping_to_schema(mapping)


@router.delete("/mappings/{mapping_id}", response_model=dict)
async def delete_mapping(
    mapping_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(SemanticMapping).where(
            SemanticMapping.id == mapping_id,
            SemanticMapping.tenant_id == tenant_id,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    await db.delete(mapping)
    await db.flush()
    return {"deleted": mapping_id}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audits", response_model=list[dict])
async def list_audits(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(DataAccessAudit)
        .where(DataAccessAudit.tenant_id == tenant_id)
        .order_by(DataAccessAudit.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": a.id,
            "role_key": a.role_key,
            "entity_name": a.entity_name,
            "semantic_concept": a.semantic_concept,
            "result_count": a.result_count,
            "success": a.success,
            "error_message": a.error_message,
            "created_at": a.created_at.isoformat(),
        }
        for a in result.scalars().all()
    ]


# ── Helper ────────────────────────────────────────────────────────────────────

def _mapping_to_schema(m: SemanticMapping) -> SemanticMappingOut:
    return SemanticMappingOut(
        id=m.id,
        tenant_id=m.tenant_id,
        semantic_concept=m.semantic_concept,
        connection_id=m.connection_id,
        entity_id=m.entity_id,
        field_name=m.field_name,
        display_label=m.display_label,
        created_by=m.created_by,
        created_at=m.created_at,
    )
