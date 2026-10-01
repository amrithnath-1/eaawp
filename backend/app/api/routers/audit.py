"""Audit log router — tenant-scoped, append-only."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import AuditLog
from app.schemas.api import AuditLogOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id

@router.get("", response_model=list[AuditLogOut])
async def list_audit_logs(
    actor: str | None = None,
    limit: int = 100,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    result = await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))
    return result.scalars().all()

# Execution traces are stored as AuditLog rows with actor="AI" and status containing
# trace metadata. A dedicated traces endpoint will be added when the orchestrator
# is integrated. For now the frontend falls back to mock traces.
@router.get("/traces", response_model=list[dict])
async def list_traces(tenant_id: str = Depends(_tenant)):
    # Returns empty list — frontend falls back to mock data when real API returns []
    return []
