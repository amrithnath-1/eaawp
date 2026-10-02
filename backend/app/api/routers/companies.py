"""GET /api/v1/companies — company management, scoped to the authenticated user's tenant."""
from __future__ import annotations

import uuid
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import Company, User
from app.db.session import get_db
from app.schemas.api import CompanyOut, CompanyCreate

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's own company only.
    Non-admin users see a single-item list containing their tenant.
    This prevents any user from enumerating other tenants' companies.
    """
    result = await db.execute(
        select(Company).where(
            Company.id == current_user.tenant_id,
            Company.is_active == True,  # noqa: E712
        )
    )
    company = result.scalar_one_or_none()
    return [company] if company else []


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a company by ID.  Users may only fetch their own tenant."""
    # Non-admins can only view their own company.
    if company_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")
    company = await db.get(Company, company_id)
    if not company or not company.is_active:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(
    body: CompanyCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new company.  Admin-only — not used during normal onboarding
    (use POST /api/v1/onboarding/company instead)."""
    company = Company(id=str(uuid.uuid4()), **body.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company
