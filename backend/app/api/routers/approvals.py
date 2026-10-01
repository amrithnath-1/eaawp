"""Approval requests router — requires authenticated user."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import get_current_user, require_admin
from app.db.models import User
from app.db.session import get_db
from app.db.models import ApprovalRequest
from app.schemas.api import ApprovalRequestOut, ApprovalDecision

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
    """Approve or reject an action.  Reviewer identity comes from the JWT, not the request body."""
    tenant_id = admin_user.tenant_id
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval or approval.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval already resolved")
    approval.status = body.decision
    # Reviewer identity is taken from the verified JWT — never from the request body.
    approval.reviewed_by = admin_user.email or admin_user.id
    approval.review_note = body.review_note
    approval.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(approval)
    return approval
