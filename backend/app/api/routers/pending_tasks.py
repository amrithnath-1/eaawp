"""
Requests waiting for an integration to be set up, and resuming them.

  GET  /api/v1/agent/pending-tasks               own waiting requests (admins: the company's)
  POST /api/v1/agent/pending-tasks/{id}/authorize admin approves read-only access for the role
  POST /api/v1/agent/pending-tasks/{id}/select-property admin chooses which site/property to report on
  POST /api/v1/agent/pending-tasks/{id}/resume    run the saved request now (if ready)
  POST /api/v1/agent/pending-tasks/{id}/cancel    drop it

Every query is tenant-scoped.  A member can only see/resume/cancel their own
requests; an admin can act on any request in their company.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, is_admin_user, require_admin
from app.db.models import AuditLog, User
from app.db.pending_task_models import PendingTask
from app.db.session import get_db
from app.integrations import manager as integration_manager
from app.schemas.blueprint import AgentBlueprint, AgentExecutionRequest, AgentExecutionResponse
from app.schemas.integration_framework import CapabilityGrantCreate
from app.services import task_readiness as readiness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent/pending-tasks", tags=["agent"])


class PendingTaskOut(BaseModel):
    id: str
    prompt: str
    role_name: str
    status: str
    blocking_state: str
    ready: bool
    next_action: str
    action_data: dict
    message: str
    created_at: str | None = None


async def _load(task_id: str, user: User, db: AsyncSession) -> PendingTask:
    row = (await db.execute(
        select(PendingTask).where(PendingTask.id == task_id, PendingTask.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    # 404 (not 403) for other users' tasks: do not confirm they exist.
    if row is None or (row.user_id != user.id and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Pending task not found")
    return row


async def _describe(task: PendingTask, user: User, db: AsyncSession) -> PendingTaskOut:
    req = readiness.requirement_of(task)
    if req is None or task.status != "waiting_setup":
        return PendingTaskOut(
            id=task.id, prompt=task.prompt, role_name=task.role_name, status=task.status,
            blocking_state="", ready=False, next_action="NONE", action_data={}, message="",
            created_at=task.created_at.isoformat() if task.created_at else None,
        )
    a = await readiness.assess(req, task.tenant_id, task.role_key, db)
    if a.ready:
        msg, action, data = "Everything is set up. You can run this request now.", "RESUME", {}
    else:
        msg, action, data = readiness.setup_message(a, is_admin=is_admin_user(user))
    data = {**data, "pending_task_id": task.id}
    return PendingTaskOut(
        id=task.id, prompt=task.prompt, role_name=task.role_name, status=task.status,
        blocking_state=a.state, ready=a.ready, next_action=action, action_data=data, message=msg,
        created_at=task.created_at.isoformat() if task.created_at else None,
    )


@router.get("", response_model=list[PendingTaskOut])
async def list_pending_tasks(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[PendingTaskOut]:
    q = select(PendingTask).where(
        PendingTask.tenant_id == user.tenant_id, PendingTask.status == "waiting_setup"
    )
    if not is_admin_user(user):
        q = q.where(PendingTask.user_id == user.id)
    rows = (await db.execute(q.order_by(PendingTask.created_at.desc()).limit(50))).scalars().all()
    return [await _describe(t, user, db) for t in rows]


@router.post("/{task_id}/authorize", response_model=PendingTaskOut)
async def authorize_pending_task(
    task_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> PendingTaskOut:
    """
    Explicit admin approval: let this task's AI role use the connected
    integration's read-only capabilities the task needs - nothing else.
    """
    task = await _load(task_id, admin, db)
    req = readiness.requirement_of(task)
    if req is None or task.status != "waiting_setup":
        raise HTTPException(status_code=409, detail="This task is not waiting for setup")
    ok, why = readiness.grantable(req)
    if not ok:
        raise HTTPException(status_code=422, detail=f"Cannot be approved in one step: {why}")
    a = await readiness.assess(req, task.tenant_id, task.role_key, db)
    if a.state != "needs_grant" or not a.integration_id:
        raise HTTPException(status_code=409, detail="Nothing to authorise yet - connect the integration first")
    for cap in a.missing_capabilities:
        await integration_manager.create_capability_grant(
            a.integration_id,
            CapabilityGrantCreate(
                role_key=task.role_key, capability_key=cap, is_granted=True, granted_by=admin.email,
            ),
            task.tenant_id, db,
        )
    db.add(AuditLog(
        id=str(uuid.uuid4()), tenant_id=task.tenant_id, ai_employee_id=None, actor=admin.email,
        event=f"admin granted {task.role_key} read access: {req.provider_type}.{','.join(a.missing_capabilities)}",
        department="admin", status="ok",
    ))
    await db.flush()
    return await _describe(task, admin, db)


class SelectPropertyBody(BaseModel):
    property_id: str


@router.post("/{task_id}/select-property", response_model=PendingTaskOut)
async def select_property(
    task_id: str, body: SelectPropertyBody,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> PendingTaskOut:
    """
    Admin picks the property (Search Console site) to report on.  The choice is
    accepted only if the connected Google account can really read it, so a
    typed or forged value cannot point the connection at someone else's site.
    """
    task = await _load(task_id, admin, db)
    req = readiness.requirement_of(task)
    if req is None or task.status != "waiting_setup" or not req.needs_property:
        raise HTTPException(status_code=409, detail="This task is not waiting for a property choice")
    a = await readiness.assess(req, task.tenant_id, task.role_key, db)
    if a.state != "needs_property" or not a.integration_id:
        raise HTTPException(status_code=409, detail="No property choice is needed right now")
    try:
        await integration_manager.set_default_property(
            a.integration_id, task.tenant_id, body.property_id, db
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.add(AuditLog(
        id=str(uuid.uuid4()), tenant_id=task.tenant_id, ai_employee_id=None, actor=admin.email,
        event=f"admin selected {req.provider_type} property for reporting",
        department="admin", status="ok",
    ))
    await db.flush()
    return await _describe(task, admin, db)


@router.post("/{task_id}/resume", response_model=AgentExecutionResponse)
async def resume_pending_task(
    task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    task = await _load(task_id, user, db)
    if task.status != "waiting_setup":
        raise HTTPException(status_code=409, detail=f"This task is already {task.status}")
    req = readiness.requirement_of(task)
    if req is not None:
        a = await readiness.assess(req, task.tenant_id, task.role_key, db)
        if not a.ready:
            msg, action, data = readiness.setup_message(a, is_admin=is_admin_user(user))
            raise HTTPException(
                status_code=409,
                detail={"message": msg, "next_action": action, "action_data": {**data, "pending_task_id": task.id}},
            )
    from app.api.routers.execution import execute_agent

    request = AgentExecutionRequest(
        blueprint=AgentBlueprint(
            agent_id=f"resume-{task.id}", role_name=task.role_name,
            system_persona="Resumed request.", tenant_id=task.tenant_id,
        ),
        user_prompt=task.prompt,
        session_id=task.session_id,
    )
    logger.info("Resuming pending task %s (owner=%s resumed_by=%s)", task.id, task.user_id, user.id)
    result = await execute_agent(request=request, tenant_id=task.tenant_id, db=db, user=user)
    # Only a run that actually completed closes the task; a failed run stays
    # open so it can be retried after the cause is fixed.
    if result.plan_status == "completed":
        task.status = "completed"
    task.resumed_plan_id = result.plan_id
    await db.flush()
    return result


@router.post("/{task_id}/cancel", response_model=PendingTaskOut)
async def cancel_pending_task(
    task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PendingTaskOut:
    task = await _load(task_id, user, db)
    if task.status == "waiting_setup":
        task.status = "cancelled"
        await db.flush()
    return await _describe(task, user, db)
