"""EAAWP Performance Analysis Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.performance_analysis import (
    analyse_campaign_performance, compare_campaigns, insight_to_dict
)

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])

@router.get("/campaigns/{campaign_id}", response_model=dict)
async def get_campaign_performance(
    campaign_id: str,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    insight = await analyse_campaign_performance(
        campaign_id=campaign_id, tenant_id=tenant_id, db=db,
        date_from=date_from, date_to=date_to,
    )
    if not insight:
        raise HTTPException(404, "Campaign not found.")
    return insight_to_dict(insight)

@router.post("/compare", response_model=dict)
async def compare_campaigns_endpoint(
    body: dict,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    campaign_ids = body.get("campaign_ids", [])
    if len(campaign_ids) < 2:
        raise HTTPException(400, "At least 2 campaign_ids required.")
    result = await compare_campaigns(
        campaign_ids=campaign_ids, tenant_id=tenant_id, db=db,
        date_from=body.get("date_from"), date_to=body.get("date_to"),
        rank_by=body.get("rank_by", "ctr"),
    )
    return {
        "campaigns": result.campaigns,
        "kpis_compared": result.kpis_compared,
        "ranked_by": result.ranked_by,
        "ranking": result.ranking,
        "insufficient_data": result.insufficient_data,
        "insufficient_reason": result.insufficient_reason,
        "sources": result.sources,
    }
