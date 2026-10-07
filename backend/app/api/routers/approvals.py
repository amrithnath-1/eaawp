"""Approval requests router — requires authenticated user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import ActionAudit, ApprovalRequest, ExecutionPlan, PlanStep, User
from app.db.session import get_db
from app.schemas.api import ApprovalDecision, ApprovalRequestOut

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRequestOut])
async def list_approvals(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current_user.tenant_id
    stmt = select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    result = await db.execute(stmt.order_by(ApprovalRequest.created_at.desc()))
    return result.scalars().all()


@router.post("/{approval_id}/decide", response_model=ApprovalRequestOut)
async def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject an action.
    Reviewer identity is taken from the verified JWT — never from the request body.
    An AuditLog record is written for every decision so the full approval
    history is queryable from the Audit page.
    """
    tenant_id = admin_user.tenant_id
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval or approval.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval already resolved")

    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Decision must be approved or rejected.")

    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.approval_request_id == approval_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    action_audit = audit_result.scalar_one_or_none()
    if not action_audit:
        raise HTTPException(status_code=409, detail="This approval has no linked action to execute.")

    reviewer = admin_user.email or admin_user.id
    step_result = await db.execute(
        select(PlanStep).where(
            PlanStep.approval_request_id == approval_id,
            PlanStep.tenant_id == tenant_id,
            PlanStep.status == "awaiting_approval",
        )
    )
    plan_step = step_result.scalar_one_or_none()

    if plan_step:
        plan = await db.get(ExecutionPlan, plan_step.plan_id)
        if not plan or plan.tenant_id != tenant_id or plan.status != "awaiting_approval":
            raise HTTPException(status_code=409, detail="The linked execution plan is no longer awaiting approval.")
        from app.services.planner import reject_plan, resume_plan

        if body.decision == "approved":
            await resume_plan(plan_id=plan.id, tenant_id=tenant_id, reviewed_by=reviewer, db=db)
        else:
            await reject_plan(plan_id=plan.id, tenant_id=tenant_id, reviewed_by=reviewer, db=db)
        from app.api.routers.planning import _sync_workflow_run_state
        await _sync_workflow_run_state(plan, db)
    else:
        # An action without a paused plan is still routed through the same
        # validation and execution service; never mark a request approved alone.
        from app.services.action_governance import approve_and_execute, reject_action

        if body.decision == "approved":
            await approve_and_execute(
                audit_id=action_audit.id,
                approval_request_id=approval_id,
                reviewed_by=reviewer,
                tenant_id=tenant_id,
                db=db,
            )
        else:
            await reject_action(
                audit_id=action_audit.id,
                approval_request_id=approval_id,
                reviewed_by=reviewer,
                tenant_id=tenant_id,
                db=db,
            )

    approval.review_note = body.review_note

    await db.commit()
    await db.refresh(approval)
    return approval
