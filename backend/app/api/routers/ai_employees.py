"""AI Employees router — tenant-scoped."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import AIEmployee
from app.schemas.api import AIEmployeeOut, AIEmployeeCreate

router = APIRouter(prefix="/api/v1/ai-employees", tags=["ai-employees"])

@router.get("", response_model=list[AIEmployeeOut])
async def list_ai_employees(
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AIEmployee).where(
            AIEmployee.tenant_id == tenant_id, AIEmployee.is_active == True
        )
    )
    return result.scalars().all()

@router.get("/{ai_employee_id}", response_model=AIEmployeeOut)
async def get_ai_employee(
    ai_employee_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    employee = await db.get(AIEmployee, ai_employee_id)
    if not employee or employee.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="AI employee not found")
    return employee

@router.post("", response_model=AIEmployeeOut, status_code=201)
async def create_ai_employee(
    body: AIEmployeeCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    employee = AIEmployee(id=str(uuid.uuid4()), tenant_id=tenant_id, **body.model_dump())
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee

@router.patch("/{ai_employee_id}/status", response_model=AIEmployeeOut)
async def update_status(
    ai_employee_id: str,
    status: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    employee = await db.get(AIEmployee, ai_employee_id)
    if not employee or employee.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="AI employee not found")
    employee.status = status
    await db.commit()
    await db.refresh(employee)
    return employee
