"""EAAWP Marketing Channel Integration Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.channel_service import (
    create_channel_integration, list_channel_integrations,
    test_channel_integration, enable_disable_channel, prepare_content_for_channel,
)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


@router.get("", response_model=list[dict])
async def list_channels(tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await list_channel_integrations(tenant_id, db)


@router.post("", response_model=dict, status_code=201, dependencies=[Depends(require_admin)])
async def create_channel(
    body: dict, tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
) -> dict:
    return await create_channel_integration(
        tenant_id=tenant_id,
        channel_type=body.get("channel_type", "custom"),
        display_name=body.get("display_name", ""),
        provider=body.get("provider", "mock"),
        credentials=body.get("credentials", {}),
        db=db,
        created_by=body.get("created_by", "admin"),
    )


@router.post("/{integration_id}/test", response_model=dict, dependencies=[Depends(require_admin)])
async def test_channel(
    integration_id: str, tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
) -> dict:
    return await test_channel_integration(integration_id, tenant_id, db)


@router.post("/{integration_id}/enable", response_model=dict, dependencies=[Depends(require_admin)])
async def enable_channel(
    integration_id: str, tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
) -> dict:
    r = await enable_disable_channel(integration_id, tenant_id, True, db)
    if not r:
        raise HTTPException(404, "Integration not found.")
    return r


@router.post("/{integration_id}/disable", response_model=dict, dependencies=[Depends(require_admin)])
async def disable_channel(
    integration_id: str, tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
) -> dict:
    r = await enable_disable_channel(integration_id, tenant_id, False, db)
    if not r:
        raise HTTPException(404, "Integration not found.")
    return r


@router.post("/{integration_id}/prepare", response_model=dict, dependencies=[Depends(require_admin)])
async def prepare_content(
    integration_id: str, body: dict,
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
) -> dict:
    return await prepare_content_for_channel(integration_id, tenant_id, body.get("content", {}), db)
