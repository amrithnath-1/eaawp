"""
EAAWP Actions Router

GET  /api/v1/actions/audits                       — list action audit records
GET  /api/v1/actions/audits/{audit_id}            — get single audit
POST /api/v1/actions/audits/{audit_id}/approve    — approve + execute
POST /api/v1/actions/audits/{audit_id}/reject     — reject (no execution)
GET  /api/v1/actions/tools                        — list registered action tools

All endpoints require X-Tenant-ID header.
Approving an action re-validates permissions before executing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.registry import ACTION_REGISTRY
from app.db.models import ActionAudit
from app.db.session import get_db
from app.schemas.actions import (
    ActionAuditOut,
    ActionApprovalDecision,
    ActionResult,
)
from app.services.action_governance import approve_and_execute, reject_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])


def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ── List registered action tools ──────────────────────────────────────────────

@router.get("/tools", response_model=list[dict])
async def list_action_tools() -> list[dict]:
    """List all registered action tools with their metadata."""
    return [
        {
            "tool_name": tool.meta.tool_name,
            "display_name": tool.meta.display_name,
            "description": tool.meta.description,
            "risk_level": tool.meta.risk_level,
            "requires_approval": tool.meta.requires_approval,
            "target_integration": tool.meta.target_integration,
            "allowed_roles": tool.meta.allowed_roles,
        }
        for tool in ACTION_REGISTRY.values()
    ]


# ── List audit records ────────────────────────────────────────────────────────

@router.get("/audits", response_model=list[ActionAuditOut])
async def list_action_audits(
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ActionAuditOut]:
    result = await db.execute(
        select(ActionAudit)
        .where(ActionAudit.tenant_id == tenant_id)
        .order_by(ActionAudit.created_at.desc())
        .limit(100)
    )
    return [ActionAuditOut.model_validate(r) for r in result.scalars().all()]


# ── Get single audit ──────────────────────────────────────────────────────────

@router.get("/audits/{audit_id}", response_model=ActionAuditOut)
async def get_action_audit(
    audit_id: str,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> ActionAuditOut:
    result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.id == audit_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Action audit record not found.")
    return ActionAuditOut.model_validate(audit)


# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/audits/{audit_id}/approve", response_model=ActionResult)
async def approve_action(
    audit_id: str,
    body: ActionApprovalDecision,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    """
    Approve a pending action and execute it.
    Re-validates arguments and permissions before execution.
    """
    if body.decision != "approved":
        raise HTTPException(status_code=400, detail="Use /reject for rejection.")

    # Load audit to get approval_request_id
    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.id == audit_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Action audit record not found.")
    if audit.approval_status != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Action is already '{audit.approval_status}' — cannot approve again.",
        )
    if not audit.approval_request_id:
        raise HTTPException(status_code=400, detail="No approval request associated with this action.")

    result = await approve_and_execute(
        audit_id=audit_id,
        approval_request_id=audit.approval_request_id,
        reviewed_by=body.reviewed_by,
        tenant_id=tenant_id,
        db=db,
    )
    return result


# ── Reject ────────────────────────────────────────────────────────────────────

@router.post("/audits/{audit_id}/reject", response_model=ActionResult)
async def reject_action_endpoint(
    audit_id: str,
    body: ActionApprovalDecision,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    """
    Reject a pending action. The action will never execute.
    Configuration is left completely unchanged.
    """
    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.id == audit_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Action audit record not found.")
    if audit.approval_status != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Action is already '{audit.approval_status}' — cannot reject again.",
        )
    if not audit.approval_request_id:
        raise HTTPException(status_code=400, detail="No approval request associated.")

    result = await reject_action(
        audit_id=audit_id,
        approval_request_id=audit.approval_request_id,
        reviewed_by=body.reviewed_by,
        tenant_id=tenant_id,
        db=db,
    )
    return result
