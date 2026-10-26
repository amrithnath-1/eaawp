"""
GET /api/v1/company-profile   any member of the company (it is what the AI employees are told about the company)
PUT /api/v1/company-profile   company administrators only; audited
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import User
from app.db.session import get_db
from app.services import company_profile as cp

router = APIRouter(prefix="/api/v1/company-profile", tags=["company-profile"])


@router.get("")
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    profile, info = await cp.load(db, user.tenant_id)
    return {"profile": profile.model_dump(), **info, "is_empty": not cp.prompt_block(profile)}


@router.put("")
async def put_profile(body: cp.CompanyProfileIn, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)) -> dict:
    await cp.save(db, admin, body)
    profile, info = await cp.load(db, admin.tenant_id)
    return {"profile": profile.model_dump(), **info, "is_empty": not cp.prompt_block(profile)}
