"""Activity events router — tenant-scoped."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import ActivityEvent
from app.core.auth import get_current_tenant_id
from app.schemas.api import ActivityEventOut

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])

@router.get("", response_model=list[ActivityEventOut])
async def list_activity(
    ai_employee_id: str | None = None,
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ActivityEvent).where(ActivityEvent.tenant_id == tenant_id)
    if ai_employee_id:
        stmt = stmt.where(ActivityEvent.ai_employee_id == ai_employee_id)
    result = await db.execute(stmt.order_by(ActivityEvent.created_at.desc()).limit(limit))
    return result.scalars().all()
