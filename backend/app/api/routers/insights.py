"""Insights router — tenant-scoped."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Insight
from app.schemas.api import InsightOut, InsightCreate

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id

@router.get("", response_model=list[InsightOut])
async def list_insights(
    ai_employee_id: str | None = None,
    include_dismissed: bool = False,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Insight).where(Insight.tenant_id == tenant_id)
    if ai_employee_id:
        stmt = stmt.where(Insight.ai_employee_id == ai_employee_id)
    if not include_dismissed:
        stmt = stmt.where(Insight.is_dismissed == False)
    result = await db.execute(stmt.order_by(Insight.detected_at.desc()))
    return result.scalars().all()

@router.post("/{insight_id}/dismiss", response_model=InsightOut)
async def dismiss_insight(
    insight_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    insight = await db.get(Insight, insight_id)
    if not insight or insight.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Insight not found")
    insight.is_dismissed = True
    await db.commit()
    await db.refresh(insight)
    return insight
