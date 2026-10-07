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


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger: str | None = None
    schedule_cron: str | None = None
    steps: list[WorkflowStep] | None = None
    is_enabled: bool | None = None


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
    Manually trigger a workflow run.
    Converts workflow steps into an execution plan via the existing planner.
    """
    tenant_id = admin_user.tenant_id
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
        )
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not wf.is_enabled:
        raise HTTPException(status_code=409, detail="Workflow is disabled")

    # Update status
    wf.status = "running"
    wf.last_run_at = datetime.now(timezone.utc)
    await db.commit()

    # Build objective from workflow steps for the planner
    steps_data = json.loads(wf.steps_json or "[]")
    step_descriptions = [s.get("description", "").strip() for s in steps_data if s.get("description", "").strip()]
    task_instructions = "; ".join(step_descriptions[:5]) or wf.description.strip() or wf.name
    objective = f"Execute workflow '{wf.name}': {task_instructions}"

    logger.info(
        "Workflow %s triggered manually for tenant %s — objective: %s",
        workflow_id, tenant_id, objective[:100],
    )

    # ── Build a minimal blueprint for the planner ─────────────────────────────
    # Use tools referenced in workflow steps plus standard safe tools.
    step_tools = [
        s.get("tool_name") for s in steps_data
        if s.get("tool_name") and isinstance(s.get("tool_name"), str)
    ]
    from app.tools.registry import MASTER_TOOL_REGISTRY
    allowed = list({t for t in step_tools if t in MASTER_TOOL_REGISTRY})
    if not allowed:
        allowed = ["query_company_data", "fetch_knowledge_base", "create_internal_task"]

    from app.schemas.blueprint import AgentBlueprint
    blueprint = AgentBlueprint(
        agent_id=f"{tenant_id}-workflow-{workflow_id[:8]}",
        role_name=wf.ai_employee_id or "Workflow Agent",
        system_persona=(
            f"You are executing the workflow '{wf.name}'. "
            f"Complete each step methodically. "
            f"Never send external communications without approval."
        ),
        allowed_tools=allowed,
        guarded_tools=["send_email"],
        tenant_id=tenant_id,
        llm_model=None,
    )

    # Set tool context for the planner
    from app.tools.registry import set_tool_context, clear_tool_context
    set_tool_context(
        db_session=db,
        tenant_id=tenant_id,
        role_key="WORKFLOW_AGENT",
        allowed_tools=allowed,
        guarded_tools=["send_email"],
    )

    try:
        from app.services.planner import create_and_execute_plan
        final_message, plan_id, tool_calls = await create_and_execute_plan(
            user_prompt=objective,
            blueprint=blueprint,
            session_id=f"workflow:{workflow_id}",
            db=db,
        )
    except Exception as exc:
        logger.error("Workflow %s execution failed: %s", workflow_id, exc)
        wf.status = "failed"
        wf.last_run_status = str(exc)[:200]
        await db.commit()
        clear_tool_context()
        return WorkflowTriggerResponse(
            workflow_id=workflow_id,
            status="failed",
            message=f"Workflow '{wf.name}' execution failed: {str(exc)[:200]}",
            plan_id=None,
        )
    finally:
        clear_tool_context()

    # Update workflow status
    plan = await db.get(ExecutionPlan, plan_id) if plan_id else None
    run_status = plan.status if plan else "failed"
    wf.status = run_status
    wf.last_run_status = run_status
    await db.commit()

    if run_status == "completed":
        message = f"Workflow '{wf.name}' completed. {final_message[:300]}"
    elif run_status == "awaiting_approval":
        message = f"Workflow '{wf.name}' is waiting for an administrator's approval. {final_message[:300]}"
    elif run_status == "rejected":
        message = f"Workflow '{wf.name}' was rejected. {final_message[:300]}"
    else:
        message = f"Workflow '{wf.name}' failed. {final_message[:300]}"

    return WorkflowTriggerResponse(
        workflow_id=workflow_id,
        status=run_status,
        message=message,
        plan_id=plan_id or None,
    )
