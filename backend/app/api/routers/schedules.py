"""Schedules router — tenant-scoped."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Schedule
from app.schemas.api import ScheduleOut, ScheduleCreate

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id

@router.get("", response_model=list[ScheduleOut])
async def list_schedules(
    ai_employee_id: str | None = None,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Schedule).where(Schedule.tenant_id == tenant_id)
    if ai_employee_id:
        stmt = stmt.where(Schedule.ai_employee_id == ai_employee_id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    ai_employee_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    schedule = Schedule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=ai_employee_id,
        **body.model_dump(),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule

@router.patch("/{schedule_id}/toggle", response_model=ScheduleOut)
async def toggle_schedule(
    schedule_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    schedule = await db.get(Schedule, schedule_id)
    if not schedule or schedule.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.status = "paused" if schedule.status == "active" else "active"
    await db.commit()
    await db.refresh(schedule)
    return schedule
