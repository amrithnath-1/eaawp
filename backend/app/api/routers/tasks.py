"""Tasks router — tenant-scoped."""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Task
from app.schemas.api import TaskOut, TaskCreate, TaskStatusUpdate

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id

@router.get("", response_model=list[TaskOut])
async def list_tasks(
    ai_employee_id: str | None = None,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Task).where(Task.tenant_id == tenant_id)
    if ai_employee_id:
        stmt = stmt.where(Task.ai_employee_id == ai_employee_id)
    result = await db.execute(stmt.order_by(Task.started_at.desc()))
    return result.scalars().all()

@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, tenant_id: str = Depends(_tenant), db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task or task.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreate,
    ai_employee_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=ai_employee_id,
        name=body.name,
        goal=body.goal,
        department=body.department,
        steps_json=json.dumps(body.steps),
        sources_json=json.dumps(body.sources),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task

@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdate,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task or task.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = body.status
    if body.progress is not None:
        task.progress = body.progress
    if body.required_action is not None:
        task.required_action = body.required_action
    if body.status == "completed":
        task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)
    return task
