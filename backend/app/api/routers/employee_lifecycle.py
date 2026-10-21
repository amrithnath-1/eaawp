"""
AI employee detail, natural-language revisions, versions, rollback and pause/resume.

All endpoints are administrator-only and tenant-scoped (another company's employee is a 404).
A revision is only a PROPOSAL until an administrator approves it.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.prompt_guard import validate_user_prompt
from app.db.employee_version_models import EmployeeVersion
from app.db.models import AIEmployee, User
from app.db.session import get_db
from app.services import employee_lifecycle as lc

router = APIRouter(prefix="/api/v1/employees", tags=["employee-lifecycle"])


class ReviseBody(BaseModel):
    instruction: str = Field(..., min_length=3, max_length=2000)


class VersionOut(BaseModel):
    id: str
    version: int
    status: str
    change_summary: str
    instruction: str
    created_by: str
    decided_by: str
    created_at: datetime
    decided_at: datetime | None
    snapshot: dict
    changes: list[dict] = []
    warnings: list[str] = []


class EmployeeDetail(BaseModel):
    id: str
    name: str
    role_key: str
    status: str
    is_active: bool
    config: dict | None
    current_version: int | None
    versions: list[VersionOut]


async def _employee(employee_id: str, admin: User, db: AsyncSession) -> AIEmployee:
    e = await db.get(AIEmployee, employee_id)
    if e is None or e.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="AI employee not found")
    return e


def _out(v: EmployeeVersion, previous: dict | None = None, warnings: list[str] | None = None) -> VersionOut:
    snap = json.loads(v.snapshot_json or "{}")
    return VersionOut(id=v.id, version=v.version, status=v.status, change_summary=v.change_summary,
                      instruction=v.instruction, created_by=v.created_by, decided_by=v.decided_by,
                      created_at=v.created_at, decided_at=v.decided_at, snapshot=snap,
                      changes=lc.diff(previous, snap) if previous is not None else [], warnings=warnings or [])


async def _detail(e: AIEmployee, db: AsyncSession) -> EmployeeDetail:
    versions = await lc.versions_of(db, e.tenant_id, e.id)
    cur = lc.current_of(versions)
    cur_snap = json.loads(cur.snapshot_json) if cur else None
    return EmployeeDetail(id=e.id, name=e.name, role_key=e.role_key, status=e.status, is_active=e.is_active,
                          config=cur_snap, current_version=cur.version if cur else None,
                          versions=[_out(v, cur_snap if v.status == "proposed" else None) for v in versions])


async def _version(e: AIEmployee, number: int, db: AsyncSession) -> EmployeeVersion:
    for v in await lc.versions_of(db, e.tenant_id, e.id):
        if v.version == number:
            return v
    raise HTTPException(status_code=404, detail="Version not found")


@router.get("/{employee_id}", response_model=EmployeeDetail)
async def get_employee(employee_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> EmployeeDetail:
    return await _detail(await _employee(employee_id, admin, db), db)


@router.post("/{employee_id}/revise", response_model=VersionOut, status_code=201)
async def revise_employee(employee_id: str, body: ReviseBody, admin: User = Depends(require_admin),
                          db: AsyncSession = Depends(get_db)) -> VersionOut:
    """Describe a change in plain language; returns a PROPOSED version with a field-by-field diff."""
    validate_user_prompt(body.instruction)
    e = await _employee(employee_id, admin, db)
    try:
        v, warnings = await lc.propose_revision(db, e.tenant_id, e, body.instruction.strip(), admin.email or admin.id)
    except lc.ValidationProblem as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    cur = lc.current_of(await lc.versions_of(db, e.tenant_id, e.id))
    await db.commit()
    return _out(v, json.loads(cur.snapshot_json) if cur else {}, warnings)


async def _decide(employee_id: str, number: int, admin: User, db: AsyncSession, action: str) -> EmployeeDetail:
    e = await _employee(employee_id, admin, db)
    v = await _version(e, number, db)
    by = admin.email or admin.id
    try:
        if action == "approve":
            await lc.approve_version(db, e.tenant_id, e, v, by)
        elif action == "reject":
            await lc.reject_version(db, e.tenant_id, e, v, by)
        else:
            await lc.rollback_to(db, e.tenant_id, e, v, by)
    except lc.ValidationProblem as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return await _detail(e, db)


@router.post("/{employee_id}/versions/{number}/approve", response_model=EmployeeDetail)
async def approve_version(employee_id: str, number: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _decide(employee_id, number, admin, db, "approve")


@router.post("/{employee_id}/versions/{number}/reject", response_model=EmployeeDetail)
async def reject_version(employee_id: str, number: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _decide(employee_id, number, admin, db, "reject")


@router.post("/{employee_id}/versions/{number}/rollback", response_model=EmployeeDetail)
async def rollback_version(employee_id: str, number: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _decide(employee_id, number, admin, db, "rollback")


class PauseBody(BaseModel):
    paused: bool


@router.post("/{employee_id}/pause", response_model=EmployeeDetail)
async def set_paused(employee_id: str, body: PauseBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> EmployeeDetail:
    """Pause: the employee cannot be asked to work (chat, Meeting Room, workflows) until resumed."""
    e = await _employee(employee_id, admin, db)
    e.status = "PAUSED" if body.paused else "ACTIVE"
    lc.audit(db, e.tenant_id, admin.email or admin.id, f"{'paused' if body.paused else 'resumed'} AI employee '{e.name}'", e.id)
    await db.commit()
    return await _detail(e, db)
