"""
EAAWP Phase H — Dynamic AI Employee Builder Router

POST /api/v1/employees/build          — NL employee creation → blueprint proposal
GET  /api/v1/employees/blueprints     — list proposals for tenant
POST /api/v1/employees/blueprints/{id}/approve — approve + activate employee
POST /api/v1/employees/blueprints/{id}/reject  — reject proposal
GET  /api/v1/employees               — list active employees for tenant

Security:
- Blueprint proposals require explicit approval before employee is created.
- Tenant_id derived from auth token (backward-compat header fallback in dev).
- LLM cannot set credentials, permissions, or bypass governance.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_tenant_id
from app.db.models import (
    AIEmployee,
    AgentConfiguration,
    EmployeeBlueprintProposalORM,
)
from app.db.session import get_db
from app.integrations import manager as mgr
from app.schemas.employee_builder import (
    EmployeeBlueprintDecision,
    EmployeeBlueprintProposal,
    EmployeeBlueprintRequest,
    EmployeeOut,
)
from app.services.employee_builder_service import generate_employee_blueprint

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/employees", tags=["employee-builder"])


def _proposal_to_schema(row: EmployeeBlueprintProposalORM) -> EmployeeBlueprintProposal:
    from app.schemas.employee_builder import RequiredCapability, MissingIntegration
    return EmployeeBlueprintProposal(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        role_key=row.role_key,
        purpose=row.purpose,
        responsibilities=json.loads(row.responsibilities_json or "[]"),
        objectives=json.loads(row.objectives_json or "[]"),
        required_capabilities=[
            RequiredCapability(**c)
            for c in json.loads(row.required_capabilities_json or "[]")
        ],
        missing_integrations=[
            MissingIntegration(**m)
            for m in json.loads(row.missing_integrations_json or "[]")
        ],
        allowed_tools=json.loads(row.allowed_tools_json or "[]"),
        guarded_tools=json.loads(row.guarded_tools_json or "[]"),
        suggested_schedule=row.suggested_schedule,
        communication_style=row.communication_style,
        llm_model=row.llm_model,
        system_persona=row.system_persona,
        approval_status=row.approval_status,  # type: ignore[arg-type]
        created_by=row.created_by,
        created_at=row.created_at,
        reviewed_by=row.reviewed_by,
        review_note=row.review_note,
    )


# ── Build new employee (NL → proposal) ───────────────────────────────────────

@router.post(
    "/build",
    response_model=EmployeeBlueprintProposal,
    status_code=201,
    summary="Build an AI employee blueprint from a natural-language description",
)
async def build_employee(
    body: EmployeeBlueprintRequest,
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmployeeBlueprintProposal:
    """
    Parse a natural-language employee creation request and return a
    blueprint proposal for human review.

    The employee is NOT created until the proposal is explicitly approved.
    Missing integrations are identified so the user knows what to connect first.
    """
    # Load existing integrations for context
    try:
        integrations = await mgr.list_integrations(tenant_id=tenant_id, db=db)
        existing = [
            {"id": i.id, "provider_type": i.provider_type, "status": i.status}
            for i in integrations
        ]
    except Exception:
        existing = []

    try:
        proposal = await generate_employee_blueprint(
            instruction=body.instruction,
            tenant_id=tenant_id,
            created_by=body.requested_by,
            existing_integrations=existing,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Persist proposal
    row = EmployeeBlueprintProposalORM(
        id=proposal.id,
        tenant_id=tenant_id,
        name=proposal.name,
        role_key=proposal.role_key,
        purpose=proposal.purpose,
        responsibilities_json=json.dumps(proposal.responsibilities),
        objectives_json=json.dumps(proposal.objectives),
        required_capabilities_json=json.dumps([rc.model_dump() for rc in proposal.required_capabilities]),
        missing_integrations_json=json.dumps([mi.model_dump() for mi in proposal.missing_integrations]),
        allowed_tools_json=json.dumps(proposal.allowed_tools),
        guarded_tools_json=json.dumps(proposal.guarded_tools),
        suggested_schedule=proposal.suggested_schedule,
        communication_style=proposal.communication_style,
        llm_model=proposal.llm_model,
        system_persona=proposal.system_persona,
        original_instruction=body.instruction,
        approval_status="pending",
        created_by=body.requested_by,
    )
    db.add(row)
    await db.commit()

    if proposal.missing_integrations:
        missing = [mi.display_name for mi in proposal.missing_integrations]
        logger.info(
            "Employee blueprint %s requires missing integrations: %s",
            proposal.id, missing,
        )

    return proposal


# ── List proposals ────────────────────────────────────────────────────────────

@router.get(
    "/blueprints",
    response_model=list[EmployeeBlueprintProposal],
    summary="List employee blueprint proposals for this tenant",
)
async def list_blueprints(
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[EmployeeBlueprintProposal]:
    result = await db.execute(
        select(EmployeeBlueprintProposalORM)
        .where(EmployeeBlueprintProposalORM.tenant_id == tenant_id)
        .order_by(EmployeeBlueprintProposalORM.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    return [_proposal_to_schema(r) for r in rows]


# ── Approve blueprint → create employee ──────────────────────────────────────

@router.post(
    "/blueprints/{proposal_id}/approve",
    response_model=EmployeeOut,
    summary="Approve blueprint and activate AI employee",
)
async def approve_blueprint(
    proposal_id: str,
    body: EmployeeBlueprintDecision,
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmployeeOut:
    """
    Approve an employee blueprint proposal.
    Creates the AIEmployee + AgentConfiguration records.
    The employee starts in ACTIVE status.
    """
    result = await db.execute(
        select(EmployeeBlueprintProposalORM).where(
            EmployeeBlueprintProposalORM.id == proposal_id,
            EmployeeBlueprintProposalORM.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Blueprint proposal not found")
    if row.approval_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is already '{row.approval_status}'",
        )
    if body.decision != "approve":
        raise HTTPException(status_code=400, detail="Use /reject for rejections")

    # Create AIEmployee
    employee_id = str(uuid.uuid4())
    employee = AIEmployee(
        id=employee_id,
        tenant_id=tenant_id,
        role_key=row.role_key,
        name=row.name,
        status="ACTIVE",
        is_active=True,
    )
    db.add(employee)

    # Create AgentConfiguration
    config = AgentConfiguration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=employee_id,
        system_persona=row.system_persona,
        tone=row.communication_style or "Concise",
        autonomy_level=3,
        capabilities_json="{}",
        tools_json=row.allowed_tools_json,
        tool_scopes_json="[]",
        permissions_json="[]",
    )
    db.add(config)

    # Mark proposal approved
    row.approval_status = "approved"
    row.reviewed_by = body.reviewed_by
    row.review_note = body.review_note
    row.ai_employee_id = employee_id

    await db.commit()
    await db.refresh(employee)

    logger.info(
        "Employee %s (%s) activated by %s in tenant %s",
        employee.name, employee.role_key, body.reviewed_by, tenant_id,
    )

    return EmployeeOut(
        id=employee.id,
        tenant_id=employee.tenant_id,
        role_key=employee.role_key,
        name=employee.name,
        status=employee.status,
        is_active=employee.is_active,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


# ── Reject blueprint ──────────────────────────────────────────────────────────

@router.post(
    "/blueprints/{proposal_id}/reject",
    response_model=EmployeeBlueprintProposal,
    summary="Reject an employee blueprint proposal",
)
async def reject_blueprint(
    proposal_id: str,
    body: EmployeeBlueprintDecision,
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmployeeBlueprintProposal:
    result = await db.execute(
        select(EmployeeBlueprintProposalORM).where(
            EmployeeBlueprintProposalORM.id == proposal_id,
            EmployeeBlueprintProposalORM.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Blueprint proposal not found")
    if row.approval_status != "pending":
        raise HTTPException(
            status_code=409, detail=f"Proposal is already '{row.approval_status}'"
        )

    row.approval_status = "rejected"
    row.reviewed_by = body.reviewed_by
    row.review_note = body.review_note
    await db.commit()
    return _proposal_to_schema(row)


# ── List active employees ─────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[EmployeeOut],
    summary="List AI employees for this tenant",
)
async def list_employees(
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[EmployeeOut]:
    result = await db.execute(
        select(AIEmployee).where(
            AIEmployee.tenant_id == tenant_id,
            AIEmployee.is_active == True,  # noqa: E712
        ).order_by(AIEmployee.created_at.desc())
    )
    employees = result.scalars().all()
    return [
        EmployeeOut(
            id=e.id,
            tenant_id=e.tenant_id,
            role_key=e.role_key,
            name=e.name,
            status=e.status,
            is_active=e.is_active,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in employees
    ]
