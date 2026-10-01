"""EAAWP Reporting Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.reporting_service import generate_marketing_summary

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


@router.get("/marketing-summary", response_model=dict)
async def marketing_summary(
    period_days: int = 7,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await generate_marketing_summary(tenant_id, db, period_days=period_days)
