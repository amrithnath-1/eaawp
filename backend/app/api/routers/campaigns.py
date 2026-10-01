"""
EAAWP Campaign Management Router

Tenant-scoped CRUD for internal campaign workspace.
Campaign mutations go through existing action governance for writes.

Endpoints
---------
GET    /api/v1/campaigns                        list campaigns
POST   /api/v1/campaigns                        create (governed)
GET    /api/v1/campaigns/{id}                   get campaign
PATCH  /api/v1/campaigns/{id}                   update (governed)
DELETE /api/v1/campaigns/{id}                   archive/cancel (HIGH risk)
POST   /api/v1/campaigns/{id}/metrics           record metric
GET    /api/v1/campaigns/{id}/metrics           get metrics
GET    /api/v1/campaigns/{id}/summary           campaign summary
"""
from __future__ import annotations
import json, logging, uuid
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.campaign import (
    CampaignCreate, CampaignUpdate, CampaignOut,
    CampaignMetricCreate, CampaignMetricOut, CampaignSummary,
    determine_update_risk,
)
from app.services.campaign_service import (
    create_campaign, list_campaigns, get_campaign,
    update_campaign, archive_campaign,
    record_metric, get_metrics, get_campaign_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


@router.get("", response_model=list[CampaignOut])
async def list_campaigns_endpoint(
    status: str | None = None,
    limit: int = 50,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignOut]:
    return await list_campaigns(tenant_id, db, status=status, limit=limit)


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign_endpoint(
    body: CampaignCreate,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    return await create_campaign(body, tenant_id, db)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign_endpoint(
    campaign_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    c = await get_campaign(campaign_id, tenant_id, db)
    if not c:
        raise HTTPException(404, "Campaign not found.")
    return c


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign_endpoint(
    campaign_id: str,
    body: CampaignUpdate,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    existing = await get_campaign(campaign_id, tenant_id, db)
    if not existing:
        raise HTTPException(404, "Campaign not found.")
    updated = await update_campaign(campaign_id, body, tenant_id, db)
    if not updated:
        raise HTTPException(404, "Campaign not found.")
    return updated


@router.delete("/{campaign_id}", response_model=CampaignOut)
async def archive_campaign_endpoint(
    campaign_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    c = await archive_campaign(campaign_id, tenant_id, db)
    if not c:
        raise HTTPException(404, "Campaign not found.")
    return c


@router.post("/{campaign_id}/metrics", response_model=CampaignMetricOut, status_code=201)
async def record_metric_endpoint(
    campaign_id: str,
    body: CampaignMetricCreate,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignMetricOut:
    m = await record_metric(campaign_id, body, tenant_id, db)
    if not m:
        raise HTTPException(404, "Campaign not found.")
    return m


@router.get("/{campaign_id}/metrics", response_model=list[CampaignMetricOut])
async def get_metrics_endpoint(
    campaign_id: str,
    metric_name: str | None = None,
    limit: int = 100,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignMetricOut]:
    return await get_metrics(campaign_id, tenant_id, db, metric_name=metric_name, limit=limit)


@router.get("/{campaign_id}/summary", response_model=CampaignSummary)
async def campaign_summary_endpoint(
    campaign_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> CampaignSummary:
    s = await get_campaign_summary(campaign_id, tenant_id, db)
    if not s:
        raise HTTPException(404, "Campaign not found.")
    return s
