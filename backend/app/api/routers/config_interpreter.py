"""
EAAWP Natural-Language Configuration Interpreter Router

POST /api/v1/roles/{role_key}/nl-configure
    Submit a natural-language instruction. Returns a proposal (not yet applied).

GET  /api/v1/roles/{role_key}/proposals
    List all proposals for a role (most recent first).

POST /api/v1/roles/{role_key}/proposals/{proposal_id}/approve
    Approve a pending proposal — applies the patch and records the audit entry.

POST /api/v1/roles/{role_key}/proposals/{proposal_id}/reject
    Reject a pending proposal — records it but leaves configuration unchanged.

Security model
--------------
- Proposals are never auto-applied. All changes require explicit approval.
- The LLM cannot change tool governance, autonomy level, LLM model, or system
  persona via this interface — those require the structured form.
- Every approved change is recorded in config_change_proposals with actor info.
- If the LLM is unavailable, the endpoint returns 503 and nothing changes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from app.db.models import User as _AuthUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.role_config import _get_or_seed, _apply_update, _orm_to_schema
from app.db.models import ConfigChangeProposal, RoleConfiguration
from app.db.session import get_db
from app.schemas.config_interpreter import (
    ConfigProposalOut,
    NLConfigRequest,
    ProposalDecision,
    ProposedChangeLine,
    ConfigChangePatch,
)
from app.schemas.role_config import IMPLEMENTED_ROLES, RoleConfigUpdate
from app.services.config_interpreter import (
    apply_patch_to_config,
    interpret_nl_instruction,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roles", tags=["nl-config"])



def _row_to_proposal(row: ConfigChangeProposal) -> ConfigProposalOut:
    """Convert an ORM row to the output schema."""
    return ConfigProposalOut(
        id=row.id,
        role_key=row.role_key,
        tenant_id=row.tenant_id,
        original_instruction=row.original_instruction,
        interpreted_intent=row.interpreted_intent,
        proposed_changes=[
            ProposedChangeLine(**c)
            for c in json.loads(row.proposed_changes_json or "[]")
        ],
        patch=ConfigChangePatch(**json.loads(row.patch_json or "{}")),
        validation_errors=json.loads(row.validation_errors_json or "[]"),
        validation_warnings=json.loads(row.validation_warnings_json or "[]"),
        approval_status=row.approval_status,  # type: ignore[arg-type]
        created_at=row.created_at,
        approved_at=row.approved_at,
        approved_by=row.approved_by,
    )


# ── Submit NL instruction → proposal ─────────────────────────────────────────

@router.post(
    "/{role_key}/nl-configure",
    response_model=ConfigProposalOut,
    summary="Interpret a natural-language configuration instruction and return a proposal",
    dependencies=[Depends(require_admin)],
)
async def nl_configure(
    role_key: str,
    body: NLConfigRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ConfigProposalOut:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available.",
            },
        )

    # Load current config (auto-seeds if missing)
    row = await _get_or_seed(role_key, tenant_id, db)
    current_config = _orm_to_schema(row)

    # Interpret with LLM — may raise RuntimeError if LLM is unavailable
    try:
        proposal = await interpret_nl_instruction(
            instruction=body.instruction,
            current_config=current_config,
            requested_by=body.requested_by,
            llm_model=current_config.llm_model,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Persist the proposal for audit purposes (status = pending)
    import uuid as _uuid_mod
    db_row = ConfigChangeProposal(
        id=proposal.id,
        tenant_id=tenant_id,
        role_key=role_key,
        original_instruction=proposal.original_instruction,
        interpreted_intent=proposal.interpreted_intent,
        proposed_changes_json=json.dumps([c.model_dump() for c in proposal.proposed_changes]),
        patch_json=json.dumps(proposal.patch.model_dump()),
        validation_errors_json=json.dumps(proposal.validation_errors),
        validation_warnings_json=json.dumps(proposal.validation_warnings),
        approval_status="pending",
        requested_by=body.requested_by,
    )
    db.add(db_row)
    await db.flush()

    return proposal


# ── List proposals ────────────────────────────────────────────────────────────

@router.get(
    "/{role_key}/proposals",
    response_model=list[ConfigProposalOut],
    summary="List all configuration change proposals for a role",
)
async def list_proposals(
    role_key: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ConfigProposalOut]:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(status_code=404, detail={"role_key": role_key, "status": "coming_soon"})

    result = await db.execute(
        select(ConfigChangeProposal)
        .where(
            ConfigChangeProposal.tenant_id == tenant_id,
            ConfigChangeProposal.role_key == role_key,
        )
        .order_by(ConfigChangeProposal.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    return [_row_to_proposal(r) for r in rows]


# ── Approve proposal ──────────────────────────────────────────────────────────

@router.post(
    "/{role_key}/proposals/{proposal_id}/approve",
    response_model=ConfigProposalOut,
    summary="Approve a pending proposal — applies the patch to the role configuration",
)
async def approve_proposal(
    role_key: str,
    proposal_id: str,
    body: ProposalDecision,
    admin_user: _AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ConfigProposalOut:
    # Tenant and reviewer identity come from the verified admin JWT, never from
    # the request body (``reviewed_by`` in the body is ignored).
    tenant_id = admin_user.tenant_id
    reviewer = admin_user.email or admin_user.id
    body.reviewed_by = reviewer
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(status_code=404, detail={"role_key": role_key, "status": "coming_soon"})

    # Fetch the proposal
    result = await db.execute(
        select(ConfigChangeProposal).where(
            ConfigChangeProposal.id == proposal_id,
            ConfigChangeProposal.tenant_id == tenant_id,
            ConfigChangeProposal.role_key == role_key,
        )
    )
    proposal_row = result.scalar_one_or_none()
    if not proposal_row:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal_row.approval_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is already '{proposal_row.approval_status}' and cannot be approved again.",
        )

    # Re-validate (guard against race conditions or tampered patches)
    patch = ConfigChangePatch(**json.loads(proposal_row.patch_json or "{}"))
    validation_errors = json.loads(proposal_row.validation_errors_json or "[]")
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail=f"Proposal has validation errors and cannot be approved: {validation_errors}",
        )

    # Load current config and build the RoleConfigUpdate to apply
    role_row = await _get_or_seed(role_key, tenant_id, db)
    current_config = _orm_to_schema(role_row)
    update_dict = apply_patch_to_config(patch, current_config)

    if update_dict:
        role_update = RoleConfigUpdate(**update_dict)
        _apply_update(role_row, role_update)

    # Mark proposal as approved
    proposal_row.approval_status = "approved"
    proposal_row.approved_by = body.reviewed_by
    proposal_row.review_note = body.review_note
    proposal_row.approved_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info(
        "Config proposal %s approved by %s for role %s / tenant %s",
        proposal_id, body.reviewed_by, role_key, tenant_id,
    )

    return _row_to_proposal(proposal_row)


# ── Reject proposal ───────────────────────────────────────────────────────────

@router.post(
    "/{role_key}/proposals/{proposal_id}/reject",
    response_model=ConfigProposalOut,
    summary="Reject a pending proposal — configuration is left unchanged",
)
async def reject_proposal(
    role_key: str,
    proposal_id: str,
    body: ProposalDecision,
    admin_user: _AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ConfigProposalOut:
    # Tenant and reviewer identity come from the verified admin JWT, never from
    # the request body (``reviewed_by`` in the body is ignored).
    tenant_id = admin_user.tenant_id
    reviewer = admin_user.email or admin_user.id
    body.reviewed_by = reviewer
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(status_code=404, detail={"role_key": role_key, "status": "coming_soon"})

    result = await db.execute(
        select(ConfigChangeProposal).where(
            ConfigChangeProposal.id == proposal_id,
            ConfigChangeProposal.tenant_id == tenant_id,
            ConfigChangeProposal.role_key == role_key,
        )
    )
    proposal_row = result.scalar_one_or_none()
    if not proposal_row:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal_row.approval_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is already '{proposal_row.approval_status}'.",
        )

    proposal_row.approval_status = "rejected"
    proposal_row.approved_by = body.reviewed_by
    proposal_row.review_note = body.review_note
    proposal_row.approved_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info(
        "Config proposal %s rejected by %s for role %s / tenant %s",
        proposal_id, body.reviewed_by, role_key, tenant_id,
    )

    return _row_to_proposal(proposal_row)
