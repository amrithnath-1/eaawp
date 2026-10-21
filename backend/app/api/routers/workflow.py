"""
EAAWP Phase I — Workflow Engine Router

POST /api/v1/workflows          — create workflow
GET  /api/v1/workflows          — list workflows for tenant
GET  /api/v1/workflows/{id}     — get workflow
PATCH /api/v1/workflows/{id}    — update workflow
DELETE /api/v1/workflows/{id}   — delete workflow
POST /api/v1/workflows/{id}/trigger — manually trigger a workflow run

A workflow is a structured sequence of steps that an AI employee executes.
Steps reference tools, actions, or approval gates.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant_id, require_admin
from app.db.models import ExecutionPlan, User, Workflow
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class WorkflowStep(BaseModel):
    step_index: int
    step_type: str = Field(..., description="tool | action | analysis | verify | response | approval_gate")
    description: str = Field(..., max_length=500)
    tool_name: str | None = None
    action_key: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    requires_approval: bool = False
    timeout_seconds: int = 60


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    trigger: str = Field(
        default="manual",
        description="manual | scheduled | event",
    )
    schedule_cron: str | None = Field(None, max_length=100)
    steps: list[WorkflowStep] = Field(default_factory=list)
    ai_employee_id: str | None = None
    is_enabled: bool = True
    created_by: str = Field(default="admin", max_length=128)
    # Run settings. The workflow runs as this AI role, attributed to the administrator
    # who saved it (taken from the verified login, never from the request body).
    role_name: str | None = Field(None, max_length=128)
    timezone: str = Field(default="UTC", max_length=64, description="IANA zone the cron schedule is read in")
    max_retries: int = Field(default=0, ge=0, le=5)
    retry_delay_minutes: int = Field(default=15, ge=1, le=1440)


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger: str | None = None
    schedule_cron: str | None = None
    steps: list[WorkflowStep] | None = None
    is_enabled: bool | None = None
    role_name: str | None = Field(None, max_length=128)
    timezone: str | None = Field(None, max_length=64)
    max_retries: int | None = Field(None, ge=0, le=5)
    retry_delay_minutes: int | None = Field(None, ge=1, le=1440)


class WorkflowOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str | None
    name: str
    description: str
    trigger: str
    schedule_cron: str | None
    steps: list[WorkflowStep]
    is_enabled: bool
    status: str
    last_run_at: datetime | None
    last_run_status: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    role_name: str | None = None
    timezone: str = "UTC"
    max_retries: int = 0
    retry_delay_minutes: int = 15

    model_config = {"from_attributes": True}


class WorkflowRunOut(BaseModel):
    id: str
    workflow_id: str
    trigger: str
    attempt: int
    status: str
    plan_id: str | None = None
    pending_task_id: str | None = None
    detail: str = ""
    not_before: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowTriggerResponse(BaseModel):
    workflow_id: str
    status: str
    message: str
    plan_id: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _orm_to_out(w: Workflow) -> WorkflowOut:
    steps_data = json.loads(w.steps_json or "[]")
    return WorkflowOut(
        id=w.id,
        tenant_id=w.tenant_id,
        ai_employee_id=w.ai_employee_id,
        name=w.name,
        description=w.description,
        trigger=w.trigger,
        schedule_cron=w.schedule_cron,
        steps=[WorkflowStep(**s) for s in steps_data],
        is_enabled=w.is_enabled,
        status=w.status,
        last_run_at=w.last_run_at,
        last_run_status=w.last_run_status,
        created_by=w.created_by,
        created_at=w.created_at,
        updated_at=w.updated_at,
        role_name=w.role_name,
        timezone=w.timezone or "UTC",
        max_retries=w.max_retries or 0,
        retry_delay_minutes=w.retry_delay_minutes or 15,
    )


_ALLOWED_TRIGGERS = frozenset(["manual", "scheduled", "event"])
_ALLOWED_STEP_TYPES = frozenset([
    "tool", "action", "analysis", "verify", "response", "approval_gate"
])


def _valid_cron(expression: str) -> bool:
    """Validate the simple five-field cron subset the scheduler implements."""
    limits = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    fields = expression.strip().split()
    if len(fields) != 5:
        return False
    for field, (minimum, maximum) in zip(fields, limits):
        if field == "*":
            continue
        if field.startswith("*/"):
            try:
                interval = int(field[2:])
            except ValueError:
                return False
            if interval < 1 or interval > maximum:
                return False
            continue
        try:
            value = int(field)
        except ValueError:
            return False
        if value < minimum or value > maximum:
            return False
    return True


def _validate_workflow(body: WorkflowCreate | WorkflowUpdate) -> None:
    if body.trigger is not None and body.trigger not in _ALLOWED_TRIGGERS:
        raise HTTPException(
            status_code=422,
            detail=f"trigger must be one of: {sorted(_ALLOWED_TRIGGERS)}",
        )
    steps = body.steps if body.steps else []
    if len(steps) > 50:
        raise HTTPException(status_code=422, detail="Workflow cannot have more than 50 steps")
    for step in steps:
        if step.step_type not in _ALLOWED_STEP_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Step type '{step.step_type}' is not allowed. Allowed: {sorted(_ALLOWED_STEP_TYPES)}",
            )
    from app.services.workflow_runner import valid_timezone
    if getattr(body, "timezone", None) is not None and not valid_timezone(body.timezone):
        raise HTTPException(status_code=422, detail="timezone must be a valid IANA zone such as 'Asia/Kolkata' or 'UTC'.")
    if body.schedule_cron is not None and not _valid_cron(body.schedule_cron):
        raise HTTPException(
            status_code=422,
            detail="schedule_cron must use five fields with *, */n, or one supported number per field.",
        )
    if isinstance(body, WorkflowCreate) and body.trigger == "scheduled":
        if not body.schedule_cron or not _valid_cron(body.schedule_cron):
            raise HTTPException(status_code=422, detail="A valid five-field schedule_cron is required for scheduled workflows.")


# ── CRUD endpoints ────────────────────────────────────────────────────────────

@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    tenant_id = admin_user.tenant_id
    _validate_workflow(body)
    wf = Workflow(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=body.ai_employee_id,
        name=body.name,
        description=body.description,
        trigger=body.trigger,
        schedule_cron=body.schedule_cron,
        steps_json=json.dumps([s.model_dump() for s in body.steps]),
        is_enabled=body.is_enabled,
        status="idle",
        created_by=admin_user.email or admin_user.id,
        role_name=body.role_name,
        run_as_user_id=admin_user.id,
        timezone=body.timezone,
        max_retries=body.max_retries,
        retry_delay_minutes=body.retry_delay_minutes,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return _orm_to_out(wf)


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowOut]:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.tenant_id == tenant_id)
        .order_by(Workflow.created_at.desc())
        .limit(100)
    )
    return [_orm_to_out(w) for w in result.scalars().all()]


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
        )
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _orm_to_out(wf)


@router.patch("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    tenant_id = admin_user.tenant_id
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
        )
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _validate_workflow(body)
    if body.name is not None:
        wf.name = body.name[:255]
    if body.description is not None:
        wf.description = body.description[:1000]
    if body.trigger is not None:
        wf.trigger = body.trigger
    if body.schedule_cron is not None:
        wf.schedule_cron = body.schedule_cron[:100]
    if body.steps is not None:
        wf.steps_json = json.dumps([s.model_dump() for s in body.steps])
    if body.is_enabled is not None:
        wf.is_enabled = body.is_enabled
    if body.role_name is not None:
        wf.role_name = body.role_name
    if body.timezone is not None:
        wf.timezone = body.timezone
    if body.max_retries is not None:
        wf.max_retries = body.max_retries
    if body.retry_delay_minutes is not None:
        wf.retry_delay_minutes = body.retry_delay_minutes
    # Saving changes makes the saving administrator responsible for future runs.
    wf.run_as_user_id = admin_user.id

    if wf.trigger == "scheduled" and (not wf.schedule_cron or not _valid_cron(wf.schedule_cron)):
        raise HTTPException(status_code=422, detail="A valid five-field schedule_cron is required for scheduled workflows.")

    await db.commit()
    await db.refresh(wf)
    return _orm_to_out(wf)


@router.delete("/{workflow_id}", status_code=204, response_model=None)
async def delete_workflow(
    workflow_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    tenant_id = admin_user.tenant_id
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
        )
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
    await db.commit()


@router.post("/{workflow_id}/trigger", response_model=WorkflowTriggerResponse)
async def trigger_workflow(
    workflow_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResponse:
    """
    Run a workflow now. Uses the same runner as scheduled runs, so the run is
    recorded in the history, the owner's permissions and the role's grants are
    re-checked, and the outcome is reported honestly.
    """
    from app.services import workflow_runner

    wf = (await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == admin_user.tenant_id)
    )).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not wf.is_enabled:
        raise HTTPException(status_code=409, detail="Workflow is disabled")
    if wf.status == "running":
        raise HTTPException(status_code=409, detail="Workflow is already running")
    await db.commit()          # release this session's snapshot before the runner opens its own

    run, status = await workflow_runner.run_now(workflow_id, admin_user.tenant_id, admin_user.id)
    if run is None:
        raise HTTPException(status_code=409, detail="Workflow could not be started")
    full = run.detail
    if run.plan_id:
        plan = await db.get(ExecutionPlan, run.plan_id)
        if plan is not None and plan.final_message:
            full = plan.final_message[:2000]      # the complete answer, not the 300-char history summary
    messages = {
        "completed": f"Workflow '{wf.name}' completed. {full}",
        "awaiting_approval": f"Workflow '{wf.name}' is waiting for an administrator's approval.",
        "waiting_setup": f"Workflow '{wf.name}' needs integration setup before it can run. {run.detail}",
        "skipped": f"Workflow '{wf.name}' was not run: {run.detail}",
        "failed": f"Workflow '{wf.name}' failed. {run.detail}",
    }
    return WorkflowTriggerResponse(
        workflow_id=workflow_id, status=status,
        message=messages.get(status, f"Workflow '{wf.name}' ended with status {status}."),
        plan_id=run.plan_id,
    )


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunOut])
async def list_workflow_runs(
    workflow_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRunOut]:
    """Execution history (newest first). Administrators only: the summaries can contain report figures."""
    from app.db.workflow_run_models import WorkflowRun
    tenant_id = admin_user.tenant_id

    wf = (await db.execute(
        select(Workflow.id).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    )).first()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    rows = (await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id, WorkflowRun.tenant_id == tenant_id)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.attempt.desc())
        .limit(100)
    )).scalars().all()
    return [WorkflowRunOut.model_validate(r) for r in rows]


@router.post("/{workflow_id}/runs/{run_id}/cancel", response_model=WorkflowRunOut)
async def cancel_workflow_run(
    workflow_id: str, run_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunOut:
    """Cancel a run that has not started (queued retry) or is waiting on setup/approval."""
    from app.db.workflow_run_models import WorkflowRun

    run = (await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.tenant_id == admin_user.tenant_id,
        )
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("queued", "waiting_setup", "awaiting_approval"):
        raise HTTPException(status_code=409, detail=f"A run that is {run.status} cannot be cancelled")

    # Cancelling must really stop the work, not only relabel it:
    #  * awaiting_approval: reject the paused plan (and its pending action) so a later
    #    approval click cannot execute it;
    #  * waiting_setup: cancel the saved pending task so it cannot be resumed into a run;
    #  * queued: the atomic queued->running claim never matches a cancelled row.
    reviewer = admin_user.email or admin_user.id
    if run.status == "awaiting_approval" and run.plan_id:
        from app.services.planner import reject_plan
        await reject_plan(plan_id=run.plan_id, tenant_id=admin_user.tenant_id, reviewed_by=reviewer, db=db)
        plan = await db.get(ExecutionPlan, run.plan_id)
        if plan is not None and plan.tenant_id == admin_user.tenant_id and plan.status == "awaiting_approval":
            raise HTTPException(status_code=409, detail="The pending action could not be stopped; try rejecting it in Approvals.")
    if run.status == "waiting_setup" and run.pending_task_id:
        from app.db.pending_task_models import PendingTask
        task = await db.get(PendingTask, run.pending_task_id)
        if task is not None and task.tenant_id == admin_user.tenant_id and task.status == "waiting_setup":
            task.status = "cancelled"
    run.status = "cancelled"
    run.detail = f"Cancelled by {admin_user.email or admin_user.id}"[:500]
    run.finished_at = datetime.now(timezone.utc)
    wf = await db.get(Workflow, workflow_id)
    if wf is not None and wf.status == "awaiting_approval":
        wf.status = "idle"
    await db.commit()
    await db.refresh(run)
    return WorkflowRunOut.model_validate(run)
