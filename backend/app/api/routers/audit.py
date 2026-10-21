"""Audit log router: tenant-scoped, append-only, administrators only (it records what every person did).

History features (Phase M): filters (text, actor, department, status, date range), bounded paging, and a CSV export
(bounded, spreadsheet-formula safe, and itself recorded in the audit log)."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant_id, require_admin
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.schemas.api import AuditLogOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

MAX_OFFSET = 100_000
EXPORT_MAX_ROWS = 5000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _bound(value: str | None, *, end: bool) -> datetime | None:
    """A date (YYYY-MM-DD, whole day, inclusive) or an ISO timestamp, as an aware UTC datetime. 422 when it is not a date."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "Dates must look like 2026-10-31 or 2026-10-31T09:30:00Z.") from None
    date_only = len(value.strip()) == 10
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    return d + timedelta(days=1) if (end and date_only) else d


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _filtered(tenant_id: str, actor: str | None, department: str | None, status: str | None, q: str | None,
              since: str | None, until: str | None):
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if department:
        stmt = stmt.where(AuditLog.department == department)
    if status:
        stmt = stmt.where(AuditLog.status == status)
    if q and q.strip():
        stmt = stmt.where(AuditLog.event.ilike(_like(q.strip()[:200]), escape="\\"))
    lo, hi = _bound(since, end=False), _bound(until, end=True)
    if lo is not None:
        stmt = stmt.where(AuditLog.created_at >= lo)
    if hi is not None:
        stmt = stmt.where(AuditLog.created_at < hi) if (until and len(until.strip()) == 10) else stmt.where(AuditLog.created_at <= hi)
    return stmt.order_by(AuditLog.created_at.desc(), AuditLog.id)


async def _names(db: AsyncSession, tenant_id: str, rows) -> dict[str, str]:
    """Many events store the acting user's id: map it to the person's name or email (same company only)."""
    ids = {r.actor for r in rows if r.actor}
    names: dict[str, str] = {}
    if ids:
        users_q = select(User).where(User.tenant_id == tenant_id, User.id.in_(ids))
        for u in (await db.execute(users_q)).scalars().all():
            names[u.id] = u.name or u.email or u.id
    return names


@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(require_admin)])
async def list_audit_logs(
    actor: str | None = None,
    department: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    q: str | None = Query(default=None, max_length=200),
    since: str | None = Query(default=None, max_length=40),
    until: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = _filtered(tenant_id, actor, department, status, q, since, until)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    names = await _names(db, tenant_id, rows)
    out = []
    for r in rows:
        item = AuditLogOut.model_validate(r)
        item.actor_name = names.get(r.actor, r.actor)
        out.append(item)
    return out


def _safe_cell(value: object) -> str:
    """Stop spreadsheet formula injection: a cell that starts with = + - @ is shown as text."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


@router.get("/export", dependencies=[Depends(require_admin)])
async def export_audit_csv(
    actor: str | None = None,
    department: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    q: str | None = Query(default=None, max_length=200),
    since: str | None = Query(default=None, max_length=40),
    until: str | None = Query(default=None, max_length=40),
    admin: User = Depends(require_admin),
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = _filtered(tenant_id, actor, department, status, q, since, until)
    rows = (await db.execute(stmt.limit(EXPORT_MAX_ROWS))).scalars().all()
    names = await _names(db, tenant_id, rows)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_utc", "actor", "actor_id", "event", "department", "status"])
    for r in rows:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        w.writerow([ts.astimezone(timezone.utc).isoformat(timespec="seconds"), _safe_cell(names.get(r.actor, r.actor)),
                    _safe_cell(r.actor), _safe_cell(r.event), _safe_cell(r.department), _safe_cell(r.status)])
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=tenant_id, actor=str(admin.id)[:64], department="audit", status="ok",
                    event=f"exported the audit log ({len(rows)} rows)"))
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit-log.csv"', "Cache-Control": "no-store"})


# Execution traces are not recorded separately yet; AI runs appear in the audit log and the Activity Center.
@router.get("/traces", response_model=list[dict])
async def list_traces(_admin: User = Depends(require_admin), tenant_id: str = Depends(get_current_tenant_id)):
    return []
