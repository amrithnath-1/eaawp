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
    result = await db.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(500))
    return await _enrich(list(result.scalars().all()), tenant_id, db)


def _reason(tool_name: str, risk: str | None) -> str:
    from app.actions.registry import get_action_tool
    tool = get_action_tool(tool_name)
    if (risk or "").lower() == "high":
        return "High-risk action: it always needs a human decision before it runs."
    if tool is not None and tool.meta.requires_approval:
        return "This kind of action always needs a human decision before it runs."
    return "The company's configuration for this AI employee requires approval for this tool."


async def _enrich(approvals: list[ApprovalRequest], tenant_id: str, db: AsyncSession) -> list[ApprovalRequestOut]:
    """Approval rows plus what they are about: AI employee, tool, risk, redacted parameters, outcome, people."""
    import json as _json

    from app.db.conversation_models import Conversation
    from app.services.action_governance import _sanitise_arguments
    from app.services.workspaces import get_workspace

    if not approvals:
        return []
    ids = [a.id for a in approvals]
    audits = {a.approval_request_id: a for a in (await db.execute(select(ActionAudit).where(
        ActionAudit.tenant_id == tenant_id, ActionAudit.approval_request_id.in_(ids)))).scalars().all()}
    steps = {st.approval_request_id: st for st in (await db.execute(select(PlanStep).where(
        PlanStep.tenant_id == tenant_id, PlanStep.approval_request_id.in_(ids)))).scalars().all()}
    plans = {pl.id: pl for pl in (await db.execute(select(ExecutionPlan).where(
        ExecutionPlan.tenant_id == tenant_id,
        ExecutionPlan.id.in_([st.plan_id for st in steps.values()])))).scalars().all()} if steps else {}
    conv_owner = dict((await db.execute(select(Conversation.id, Conversation.user_id).where(
        Conversation.tenant_id == tenant_id,
        Conversation.id.in_([pl.session_id for pl in plans.values() if pl.session_id])))).all()) if plans else {}
    people = {u.id: u for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all()}
    by_email = {u.email: u for u in people.values()}

    out = []
    for a in approvals:
        row = ApprovalRequestOut.model_validate(a)
        audit, step = audits.get(a.id), steps.get(a.id)
        if audit is not None:
            w = get_workspace(audit.role_key)
            try:
                params = _sanitise_arguments(_json.loads(audit.arguments_json or "{}"))
            except ValueError:
                params = {}
            row.ai_employee = w.name if w else audit.role_key.replace("_", " ").title()
            row.tool_name, row.risk_level = audit.tool_name, audit.risk_level
            row.parameters = {k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:500])
                              for k, v in list(params.items())[:20]}
            row.reason = _reason(audit.tool_name, audit.risk_level)
            row.execution_status, row.execution_error = audit.execution_status, audit.error_message
        if step is not None and step.plan_id in plans:
            plan = plans[step.plan_id]
            row.plan_id, row.plan_status = plan.id, plan.status
            owner = people.get(conv_owner.get(plan.session_id or "", ""))
            row.requested_for = owner.name if owner else None
        reviewer = by_email.get(a.reviewed_by or "") or people.get(a.reviewed_by or "")
        row.reviewer_name = reviewer.name if reviewer else (a.reviewed_by or None)
        out.append(row)
    return out


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
        from app.api.routers.planning import _sync_conversation, _sync_workflow_run_state
        await _sync_workflow_run_state(plan, db)
        await db.refresh(plan)
        steps = list((await db.execute(select(PlanStep).where(
            PlanStep.plan_id == plan.id, PlanStep.tenant_id == tenant_id))).scalars().all())
        await _sync_conversation(plan, steps, db)
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
    return (await _enrich([approval], tenant_id, db))[0]
