"""
EAAWP Admin AI Customization Router

POST /api/v1/admin/customize/plan     — parse NL instruction → structured plan
POST /api/v1/admin/customize/execute  — confirm + execute a validated plan

Security:
- Both endpoints require Company Admin role (enforced by require_admin dependency).
- Non-admin users receive HTTP 403 — role is verified via JWT, not just UI hiding.
- Tenant_id is derived from the authenticated user's JWT — never from the request body.
- The LLM never receives credentials, API keys, or tokens.
- The plan is re-validated before execution.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.admin_customization import (
    AdminCustomizationConfirmRequest,
    AdminCustomizationRequest,
    AdminCustomizationResult,
    CustomizationPlan,
)
from app.services.admin_customization_service import (
    execute_customization_plan,
    generate_customization_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/customize", tags=["admin-customization"])


@router.post(
    "/plan",
    response_model=CustomizationPlan,
    summary="Generate a customization plan from a natural-language admin instruction",
    description=(
        "Company Admin only. Parses the instruction using the LLM Gateway and returns "
        "a structured plan for review. No changes are applied until /execute is called. "
        "The LLM never receives credentials, tokens, or secrets."
    ),
)
async def generate_plan(
    body: AdminCustomizationRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CustomizationPlan:
    """
    Parse a natural-language instruction into a structured customization plan.

    Returns a plan with operations, missing information, and a summary.
    The plan must be confirmed via /execute before any changes are applied.

    Requires: Company Admin role (403 otherwise).
    Tenant_id is derived from the authenticated admin's JWT.
    """
    tenant_id = admin_user.tenant_id

    logger.info(
        "Admin customization plan requested: tenant=%s user=%s",
        tenant_id, admin_user.id,
    )

    try:
        plan = await generate_customization_plan(
            instruction=body.instruction,
            tenant_id=tenant_id,
            requested_by=admin_user.email or admin_user.id,
            db=db,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return plan


@router.post(
    "/execute",
    response_model=AdminCustomizationResult,
    summary="Execute a confirmed customization plan",
    description=(
        "Company Admin only. Validates and executes a previously generated plan "
        "through existing EAAWP services. The plan is re-validated before execution. "
        "HIGH-risk operations still go through the existing approval pipeline."
    ),
)
async def execute_plan(
    body: AdminCustomizationConfirmRequest,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCustomizationResult:
    """
    Execute a confirmed customization plan through existing EAAWP services.

    The plan is re-validated on the backend before any operation is executed.
    Each operation maps to an existing service function — no business logic
    is duplicated in this endpoint.

    Requires: Company Admin role (403 otherwise).
    Tenant_id is derived from the authenticated admin's JWT.
    """
    tenant_id = admin_user.tenant_id

    logger.info(
        "Admin customization execution requested: tenant=%s user=%s operations=%d",
        tenant_id, admin_user.id, len(body.plan.operations),
    )

    try:
        result = await execute_customization_plan(
            plan=body.plan,
            tenant_id=tenant_id,
            confirmed_by=admin_user.email or admin_user.id,
            db=db,
            admin=admin_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Admin customization execution error for tenant %s", tenant_id)
        raise HTTPException(
            status_code=500,
            detail="Customization execution failed. See backend logs for details.",
        ) from exc

    return result
