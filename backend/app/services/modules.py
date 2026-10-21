"""
Module catalog and per-company activation (Phase L).

A "module" is a packaged AI employee role a company can use. Activation is a per-company switch an administrator controls.
No activation row means "use the catalog default", so existing companies keep working; a later billing step can flip a
module's default to False without touching enforcement. Deactivation blocks use but never deletes any data.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import AuditLog, User
from app.db.module_models import ModuleActivation
from app.db.session import get_db


@dataclass(frozen=True)
class ModuleDef:
    key: str
    name: str
    description: str
    category: str
    status: str = "available"          # available | coming_soon
    default_active: bool = True


CATALOG: tuple[ModuleDef, ...] = (
    ModuleDef("DIGITAL_MARKETING_MANAGER", "Digital Marketing Manager", "Plans campaigns, writes content, and reads Google Analytics and Search Console.", "Marketing"),
    ModuleDef("DATA_INTELLIGENCE_ANALYST", "Data Analyst", "Answers questions from your connected company data and builds reports.", "Data"),
    ModuleDef("INSTITUTIONAL_CLERK", "Institutional Clerk", "Handles student and staff requests and drafts official documents for approval.", "Administration"),
    ModuleDef("MEDICAL_ASSISTANT", "Medical Assistant", "Manages appointments and patient messages with strict privacy controls.", "Healthcare"),
    ModuleDef("SEO_SPECIALIST", "SEO Specialist", "Search ranking audits and content optimisation.", "Marketing", "coming_soon", False),
    ModuleDef("HR_MANAGER", "HR Manager", "Hiring, onboarding and policy questions.", "People", "coming_soon", False),
    ModuleDef("CYBERSECURITY_ANALYST", "Cybersecurity Analyst", "Monitors alerts and reviews access.", "Security", "coming_soon", False),
    ModuleDef("FINANCIAL_ADVISOR", "Financial Advisor", "Budget tracking and financial summaries.", "Finance", "coming_soon", False),
    ModuleDef("PROJECT_MANAGER", "Project Manager", "Plans projects, tracks tasks and reports status.", "Operations", "coming_soon", False),
)
_BY_KEY = {m.key: m for m in CATALOG}


def get_module(key: str) -> ModuleDef | None:
    return _BY_KEY.get(key)


def module_for_role(role_key: str) -> str | None:
    """The catalog module a role key belongs to; custom or unknown roles are not module-gated."""
    m = _BY_KEY.get(role_key)
    return m.key if m and m.status == "available" else None


async def _row(db: AsyncSession, tenant_id: str, key: str) -> ModuleActivation | None:
    return (await db.execute(select(ModuleActivation).where(
        ModuleActivation.tenant_id == tenant_id, ModuleActivation.module_key == key))).scalar_one_or_none()


async def is_module_active(db: AsyncSession, tenant_id: str, key: str) -> bool:
    m = _BY_KEY.get(key)
    if m is None or m.status != "available":
        return False
    row = await _row(db, tenant_id, key)
    return row.active if row is not None else m.default_active


async def list_modules(db: AsyncSession, tenant_id: str) -> list[dict]:
    rows = {r.module_key: r for r in (await db.execute(
        select(ModuleActivation).where(ModuleActivation.tenant_id == tenant_id))).scalars().all()}
    out = []
    for m in CATALOG:
        r = rows.get(m.key)
        active = m.status == "available" and (r.active if r is not None else m.default_active)
        out.append({"key": m.key, "name": m.name, "description": m.description, "category": m.category, "status": m.status,
                    "active": bool(active), "changed_at": r.changed_at if r else None})
    return out


async def set_active(db: AsyncSession, admin: User, key: str, active: bool) -> dict:
    m = _BY_KEY.get(key)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    if m.status != "available":
        raise HTTPException(status_code=409, detail=f"{m.name} is not available yet.")
    row = await _row(db, admin.tenant_id, key)
    if row is None:
        row = ModuleActivation(id=str(uuid.uuid4()), tenant_id=admin.tenant_id, module_key=key, active=active, changed_by=admin.id)
        db.add(row)
    elif row.active != active:
        row.active, row.changed_by = active, admin.id
    else:
        return next(x for x in await list_modules(db, admin.tenant_id) if x["key"] == key)       # already in that state
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=admin.tenant_id, actor=str(admin.id)[:64],
                    event=f"module {m.name} {'activated' if active else 'deactivated'}"[:500], department="marketplace", status="ok"))
    await db.flush()
    await db.refresh(row)
    return next(x for x in await list_modules(db, admin.tenant_id) if x["key"] == key)


def require_module(key: str):
    """Router/route dependency: 403 unless the caller's company has the module active."""
    m = _BY_KEY[key]

    async def _dep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
        if not await is_module_active(db, user.tenant_id, key):
            raise HTTPException(status_code=403, detail=f"The {m.name} module is not activated for your company. A company administrator can activate it from the Marketplace.")
    return _dep
