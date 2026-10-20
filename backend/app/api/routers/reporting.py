"""EAAWP Reporting Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.reporting_service import generate_marketing_summary

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/marketing-summary", response_model=dict)
async def marketing_summary(
    period_days: int = 7,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await generate_marketing_summary(tenant_id, db, period_days=period_days)
