"""
EAAWP Data Integration Router

Manages company external data source connections.

Endpoints
---------
POST   /api/v1/integrations/connections           — create connection
GET    /api/v1/integrations/connections           — list connections
GET    /api/v1/integrations/connections/{id}      — get one connection
PATCH  /api/v1/integrations/connections/{id}      — update connection
DELETE /api/v1/integrations/connections/{id}      — delete connection
POST   /api/v1/integrations/connections/{id}/test — test connection
POST   /api/v1/integrations/connections/{id}/discover — discover schema
GET    /api/v1/integrations/connections/{id}/entities — list discovered entities
PATCH  /api/v1/integrations/entities/{entity_id}/permission — set allowed flag
POST   /api/v1/integrations/connections/{id}/entities/bulk-permission — bulk set

Security
--------
- encrypted_password is NEVER returned in any response.
- All endpoints are tenant-scoped via X-Tenant-ID header.
- Connection tests are the only operations that use the live external DB.
- Schema discovery returns metadata only — no data rows.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataConnection, SchemaEntity
from app.db.session import get_db
from app.integrations.connector import get_connector
from app.integrations.crypto import decrypt_password, encrypt_password
from app.schemas.integration import (
    BulkEntityPermissionUpdate,
    ColumnMetaOut,
    ConnectionTestResponse,
    DataConnectionCreate,
    DataConnectionOut,
    DataConnectionUpdate,
    EntityPermissionUpdate,
    SchemaEntityOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])



def _conn_to_schema(conn: DataConnection, entity_count: int = 0, allowed_count: int = 0) -> DataConnectionOut:
    return DataConnectionOut(
        id=conn.id,
        tenant_id=conn.tenant_id,
        display_name=conn.display_name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database_name=conn.database_name,
        username=conn.username,
        ssl_required=conn.ssl_required,
        status=conn.status,  # type: ignore[arg-type]
        last_tested_at=conn.last_tested_at,
        error_message=conn.error_message,
        created_by=conn.created_by,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
        entity_count=entity_count,
        allowed_entity_count=allowed_count,
    )


async def _get_conn_or_404(conn_id: str, tenant_id: str, db: AsyncSession) -> DataConnection:
    result = await db.execute(
        select(DataConnection).where(
            DataConnection.id == conn_id,
            DataConnection.tenant_id == tenant_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return conn


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/connections", response_model=DataConnectionOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_connection(
    body: DataConnectionCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DataConnectionOut:
    encrypted = encrypt_password(body.password)
    conn = DataConnection(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        display_name=body.display_name,
        db_type=body.db_type,
        host=body.host,
        port=body.port,
        database_name=body.database_name,
        username=body.username,
        encrypted_password=encrypted,
        ssl_required=body.ssl_required,
        status="not_tested",
        created_by=body.created_by,
    )
    db.add(conn)
    await db.flush()
    return _conn_to_schema(conn)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/connections", response_model=list[DataConnectionOut])
async def list_connections(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[DataConnectionOut]:
    result = await db.execute(
        select(DataConnection)
        .where(DataConnection.tenant_id == tenant_id)
        .order_by(DataConnection.created_at.desc())
    )
    connections = result.scalars().all()
    output = []
    for conn in connections:
        # Count entities for each connection
        ec_result = await db.execute(
            select(SchemaEntity.id, SchemaEntity.is_allowed)
            .where(SchemaEntity.connection_id == conn.id)
        )
        entity_rows = ec_result.fetchall()
        total = len(entity_rows)
        allowed = sum(1 for r in entity_rows if r.is_allowed)
        output.append(_conn_to_schema(conn, total, allowed))
    return output


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}", response_model=DataConnectionOut)
async def get_connection(
    conn_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DataConnectionOut:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)
    ec_result = await db.execute(
        select(SchemaEntity.id, SchemaEntity.is_allowed)
        .where(SchemaEntity.connection_id == conn_id)
    )
    entity_rows = ec_result.fetchall()
    return _conn_to_schema(conn, len(entity_rows), sum(1 for r in entity_rows if r.is_allowed))


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/connections/{conn_id}", response_model=DataConnectionOut, dependencies=[Depends(require_admin)])
async def update_connection(
    conn_id: str,
    body: DataConnectionUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DataConnectionOut:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)
    if body.display_name is not None:
        conn.display_name = body.display_name
    if body.host is not None:
        conn.host = body.host
    if body.port is not None:
        conn.port = body.port
    if body.database_name is not None:
        conn.database_name = body.database_name
    if body.username is not None:
        conn.username = body.username
    if body.password is not None:
        conn.encrypted_password = encrypt_password(body.password)
        conn.status = "not_tested"  # force re-test after credential change
    if body.ssl_required is not None:
        conn.ssl_required = body.ssl_required
    await db.flush()
    return _conn_to_schema(conn)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/connections/{conn_id}", response_model=dict, dependencies=[Depends(require_admin)])
async def delete_connection(
    conn_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)
    await db.delete(conn)
    await db.flush()
    return {"deleted": conn_id}


# ── Test connection ───────────────────────────────────────────────────────────

@router.post("/connections/{conn_id}/test", response_model=ConnectionTestResponse, dependencies=[Depends(require_admin)])
async def test_connection(
    conn_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ConnectionTestResponse:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)

    # Mark as testing
    conn.status = "testing"
    await db.flush()

    try:
        connector = get_connector(conn.db_type)
        password = decrypt_password(conn.encrypted_password)
        result = await connector.test_connection(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=password,
            ssl=conn.ssl_required,
        )
    except Exception as exc:
        logger.error("Connection test error for %s: %s", conn_id, exc)
        result_success = False
        result_error = str(exc)[:300]
        result_version = None
    else:
        result_success = result.success
        result_error = result.error_message
        result_version = result.server_version

    # Update status — only "connected" if the test actually succeeded
    conn.status = "connected" if result_success else "failed"
    conn.last_tested_at = datetime.now(timezone.utc)
    conn.error_message = result_error
    await db.flush()

    return ConnectionTestResponse(
        connection_id=conn_id,
        success=result_success,
        status=conn.status,  # type: ignore[arg-type]
        server_version=result_version,
        error_message=result_error,
    )


# ── Discover schema ───────────────────────────────────────────────────────────

@router.post("/connections/{conn_id}/discover", response_model=list[SchemaEntityOut], dependencies=[Depends(require_admin)])
async def discover_schema(
    conn_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SchemaEntityOut]:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)

    if conn.status != "connected":
        raise HTTPException(
            status_code=400,
            detail="Connection must be tested and confirmed before schema discovery.",
        )

    try:
        connector = get_connector(conn.db_type)
        password = decrypt_password(conn.encrypted_password)
        entities = await connector.discover_schema(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=password,
            ssl=conn.ssl_required,
        )
    except Exception as exc:
        logger.error("Schema discovery failed for %s: %s", conn_id, exc)
        raise HTTPException(status_code=503, detail=f"Schema discovery failed: {exc}") from exc

    # Upsert schema entities — preserve existing is_allowed flags
    existing_result = await db.execute(
        select(SchemaEntity).where(SchemaEntity.connection_id == conn_id)
    )
    existing: dict[tuple[str, str], SchemaEntity] = {
        (e.schema_name, e.entity_name): e
        for e in existing_result.scalars().all()
    }

    now = datetime.now(timezone.utc)
    output: list[SchemaEntityOut] = []

    for meta in entities:
        key = (meta.schema_name, meta.entity_name)
        cols_json = json.dumps([
            {
                "name": c.name,
                "data_type": c.data_type,
                "is_nullable": c.is_nullable,
                "is_primary_key": c.is_primary_key,
            }
            for c in meta.columns
        ])
        if key in existing:
            entity = existing[key]
            entity.columns_json = cols_json
            entity.entity_type = meta.entity_type
            entity.row_count_estimate = meta.row_count_estimate
            entity.discovered_at = now
        else:
            entity = SchemaEntity(
                id=str(uuid.uuid4()),
                connection_id=conn_id,
                tenant_id=tenant_id,
                schema_name=meta.schema_name,
                entity_name=meta.entity_name,
                entity_type=meta.entity_type,
                columns_json=cols_json,
                row_count_estimate=meta.row_count_estimate,
                is_allowed=False,
                discovered_at=now,
            )
            db.add(entity)

        await db.flush()
        output.append(_entity_to_schema(entity))

    return output


# ── List entities ─────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/entities", response_model=list[SchemaEntityOut])
async def list_entities(
    conn_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SchemaEntityOut]:
    conn = await _get_conn_or_404(conn_id, tenant_id, db)
    result = await db.execute(
        select(SchemaEntity)
        .where(
            SchemaEntity.connection_id == conn.id,
            SchemaEntity.tenant_id == tenant_id,
        )
        .order_by(SchemaEntity.schema_name, SchemaEntity.entity_name)
    )
    return [_entity_to_schema(e) for e in result.scalars().all()]


# ── Set entity permission ─────────────────────────────────────────────────────

@router.patch("/entities/{entity_id}/permission", response_model=SchemaEntityOut, dependencies=[Depends(require_admin)])
async def set_entity_permission(
    entity_id: str,
    body: EntityPermissionUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SchemaEntityOut:
    result = await db.execute(
        select(SchemaEntity).where(
            SchemaEntity.id == entity_id,
            SchemaEntity.tenant_id == tenant_id,
        )
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found.")
    entity.is_allowed = body.is_allowed
    await db.flush()
    return _entity_to_schema(entity)


# ── Bulk permission ───────────────────────────────────────────────────────────

@router.post("/connections/{conn_id}/entities/bulk-permission", response_model=dict, dependencies=[Depends(require_admin)])
async def bulk_set_permission(
    conn_id: str,
    body: BulkEntityPermissionUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_conn_or_404(conn_id, tenant_id, db)
    result = await db.execute(
        select(SchemaEntity).where(
            SchemaEntity.connection_id == conn_id,
            SchemaEntity.tenant_id == tenant_id,
            SchemaEntity.id.in_(body.entity_ids),
        )
    )
    entities = result.scalars().all()
    for entity in entities:
        entity.is_allowed = body.is_allowed
    await db.flush()
    return {"updated": len(entities), "is_allowed": body.is_allowed}


# ── Helper ────────────────────────────────────────────────────────────────────

def _entity_to_schema(entity: SchemaEntity) -> SchemaEntityOut:
    cols_raw: list[dict] = json.loads(entity.columns_json or "[]")
    columns = [
        ColumnMetaOut(
            name=c.get("name", ""),
            data_type=c.get("data_type", ""),
            is_nullable=bool(c.get("is_nullable", True)),
            is_primary_key=bool(c.get("is_primary_key", False)),
        )
        for c in cols_raw
    ]
    return SchemaEntityOut(
        id=entity.id,
        connection_id=entity.connection_id,
        schema_name=entity.schema_name,
        entity_name=entity.entity_name,
        entity_type=entity.entity_type,
        columns=columns,
        row_count_estimate=entity.row_count_estimate,
        is_allowed=entity.is_allowed,
        discovered_at=entity.discovered_at,
    )
