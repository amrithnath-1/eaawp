"""
EAAWP Planning Router

GET  /api/v1/planning/plans                 — list plans for tenant
GET  /api/v1/planning/plans/{plan_id}       — get plan + steps
POST /api/v1/planning/plans/{plan_id}/resume — resume after approval

All endpoints require X-Tenant-ID header.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionPlan, PlanStep
from app.db.session import get_db
from app.schemas.planning import ExecutionPlanOut, PlanResumeRequest, PlanStepOut
from app.services.planner import resume_plan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


def _step_out(s: PlanStep) -> PlanStepOut:
    import json
    return PlanStepOut(
        step_id=s.id,
        plan_id=s.plan_id,
        step_index=s.step_index,
        step_type=s.step_type,  # type: ignore[arg-type]
        description=s.description,
        tool_name=s.tool_name,
        arguments_json=s.arguments_json,
        depends_on=json.loads(s.depends_on_json or "[]"),
        status=s.status,  # type: ignore[arg-type]
        result_summary=s.result_summary,
        approval_request_id=s.approval_request_id,
        action_audit_id=s.action_audit_id,
        created_at=s.created_at,
        completed_at=s.completed_at,
    )


def _plan_out(plan: ExecutionPlan, steps: list[PlanStep]) -> ExecutionPlanOut:
    return ExecutionPlanOut(
        id=plan.id,
        tenant_id=plan.tenant_id,
        role_key=plan.role_key,
        session_id=plan.session_id,
        objective=plan.objective,
        status=plan.status,  # type: ignore[arg-type]
        total_steps=plan.total_steps,
        completed_steps=plan.completed_steps,
        tool_calls_used=plan.tool_calls_used,
        final_message=plan.final_message,
        error_message=plan.error_message,
        steps=[_step_out(s) for s in sorted(steps, key=lambda s: s.step_index)],
        created_at=plan.created_at,
        completed_at=plan.completed_at,
    )


@router.get("/plans", response_model=list[ExecutionPlanOut])
async def list_plans(
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionPlanOut]:
    plan_result = await db.execute(
        select(ExecutionPlan)
        .where(ExecutionPlan.tenant_id == tenant_id)
        .order_by(ExecutionPlan.created_at.desc())
        .limit(50)
    )
    plans = plan_result.scalars().all()
    output = []
    for plan in plans:
        steps_result = await db.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id)
        )
        output.append(_plan_out(plan, list(steps_result.scalars().all())))
    return output


@router.get("/plans/{plan_id}", response_model=ExecutionPlanOut)
async def get_plan(
    plan_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> ExecutionPlanOut:
    plan_result = await db.execute(
        select(ExecutionPlan).where(
            ExecutionPlan.id == plan_id,
            ExecutionPlan.tenant_id == tenant_id,
        )
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    steps_result = await db.execute(
        select(PlanStep).where(PlanStep.plan_id == plan_id)
    )
    return _plan_out(plan, list(steps_result.scalars().all()))


@router.post("/plans/{plan_id}/resume", response_model=ExecutionPlanOut)
async def resume_plan_endpoint(
    plan_id: str,
    body: PlanResumeRequest,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> ExecutionPlanOut:
    """Resume a paused plan after an action approval. Re-validates permissions."""
    final_message, _ = await resume_plan(
        plan_id=plan_id,
        tenant_id=tenant_id,
        reviewed_by=body.reviewed_by,
        db=db,
    )
    plan_result = await db.execute(
        select(ExecutionPlan).where(
            ExecutionPlan.id == plan_id,
            ExecutionPlan.tenant_id == tenant_id,
        )
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    steps_result = await db.execute(
        select(PlanStep).where(PlanStep.plan_id == plan_id)
    )
    return _plan_out(plan, list(steps_result.scalars().all()))
