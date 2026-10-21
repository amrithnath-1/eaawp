"""Marketplace API (Phase L): see the module catalog, and (administrators) activate or deactivate modules for the company."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import User
from app.db.session import get_db
from app.services import modules as ms

router = APIRouter(prefix="/api/v1/modules", tags=["marketplace"])


class ModuleOut(BaseModel):
    key: str
    name: str
    description: str
    category: str
    status: str
    active: bool
    changed_at: datetime | None = None


@router.get("", response_model=list[ModuleOut])
async def list_modules(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await ms.list_modules(db, user.tenant_id)


@router.post("/{key}/activate", response_model=ModuleOut)
async def activate(key: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    return await ms.set_active(db, admin, key, True)


@router.post("/{key}/deactivate", response_model=ModuleOut)
async def deactivate(key: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    return await ms.set_active(db, admin, key, False)
