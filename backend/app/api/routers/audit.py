"""Audit log router — tenant-scoped, append-only, administrators only (it records what every person did)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import AuditLog, User
from app.schemas.api import AuditLogOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(require_admin)])
async def list_audit_logs(
    actor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    # Many events store the acting user's id: show a person's name or email instead of an opaque id.
    ids = {r.actor for r in rows if r.actor}
    names: dict[str, str] = {}
    if ids:
        users_q = select(User).where(User.tenant_id == tenant_id, User.id.in_(ids))
        for u in (await db.execute(users_q)).scalars().all():
            names[u.id] = u.name or u.email or u.id
    out = []
    for r in rows:
        item = AuditLogOut.model_validate(r)
        item.actor_name = names.get(r.actor, r.actor)
        out.append(item)
    return out

# Execution traces are not recorded separately yet; AI runs appear in the audit log and the Activity Center.
@router.get("/traces", response_model=list[dict])
async def list_traces(_admin: User = Depends(require_admin), tenant_id: str = Depends(get_current_tenant_id)):
    return []
