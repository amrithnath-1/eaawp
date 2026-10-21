"""
Clinic support API (Medical Assistant). Not a clinical system: no diagnosis, no advice.

Any member: request an appointment for THEMSELVES, see/cancel/message on their own requests.
Administrators (clinic staff): the company's requests (urgent wording first), confirm / reschedule / complete,
internal notes, intake summaries, erase a record. Every administrator access to someone else's record is audited.
Another company's data is always a 404.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, is_admin_user, require_admin
from app.db.medical_models import Appointment
from app.db.models import User
from app.db.session import get_db
from app.services import medical_guard as guard
from app.services import medical_service as ms

router = APIRouter(prefix="/api/v1/clinic", tags=["medical-assistant"])


class AppointmentCreate(BaseModel):
    reason: str = Field(..., min_length=3, max_length=3000)
    preferred_time: str = Field(default="", max_length=80)
    contact: str = Field(default="", max_length=120)


class NoteBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    internal: bool = False


class StatusBody(BaseModel):
    status: str
    scheduled_for: str | None = Field(default=None, max_length=25)
    clinician_name: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)


class ScreenBody(BaseModel):
    text: str = Field(..., max_length=3000)


class NoteOut(BaseModel):
    at: str
    by_name: str
    text: str
    internal: bool


class AppointmentOut(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    contact: str
    reason: str
    preferred_time: str
    status: str
    scheduled_for: str | None
    clinician_name: str
    red_flag: bool
    red_flags: list[str]
    intake: dict
    notes: list[NoteOut]
    emergency_notice: str | None = None
    disclaimer: str = guard.DISCLAIMER
    created_at: datetime
    updated_at: datetime


def _fail(exc: ms.MedicalError):
    raise HTTPException(status_code=exc.status, detail=str(exc))


async def _out(a: Appointment, user: User, db: AsyncSession, notice: bool = False) -> AppointmentOut:
    await db.refresh(a)
    admin = is_admin_user(user)
    notes = [NoteOut(at=n.get("at", ""), by_name=n.get("by_name", ""), text=n.get("text", ""), internal=bool(n.get("internal")))
             for n in ms.notes_of(a) if admin or not n.get("internal")]
    return AppointmentOut(id=a.id, patient_id=a.patient_id, patient_name=a.patient_name, contact=a.contact, reason=a.reason,
                          preferred_time=a.preferred_time, status=a.status, scheduled_for=a.scheduled_for, clinician_name=a.clinician_name,
                          red_flag=a.red_flag, red_flags=json.loads(a.red_flags_json or "[]"), intake=json.loads(a.intake_json or "{}"),
                          notes=notes, emergency_notice=guard.EMERGENCY_MESSAGE if (notice and a.red_flag) else None,
                          created_at=a.created_at, updated_at=a.updated_at)


async def _load(appointment_id: str, user: User, db: AsyncSession, view: bool = False) -> Appointment:
    a = await ms.get(db, user.tenant_id, appointment_id)
    if a is None or (a.patient_id != user.id and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Appointment not found")
    if view and a.patient_id != user.id:
        ms.audit(db, user.tenant_id, user.email or user.id, f"staff viewed appointment record {a.id[:8]}")
    return a


@router.get("/meta")
async def meta(user: User = Depends(get_current_user)) -> dict:
    return {"disclaimer": guard.DISCLAIMER, "statuses": list(ms.TRANSITIONS), "is_staff": is_admin_user(user)}


@router.post("/screen")
async def screen(body: ScreenBody, user: User = Depends(get_current_user)) -> dict:
    g = guard.screen(body.text)
    return {"kind": g.kind, "message": g.message} if g else {"kind": None, "message": None}


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def create(body: AppointmentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    try:
        a = await ms.create(db, user, body.reason, body.preferred_time, body.contact)
    except ms.MedicalError as exc:
        _fail(exc)
    await db.commit()
    return await _out(a, user, db, notice=True)


@router.get("/appointments", response_model=list[AppointmentOut])
async def list_appointments(status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[AppointmentOut]:
    q = select(Appointment).where(Appointment.tenant_id == user.tenant_id)
    if not is_admin_user(user):
        q = q.where(Appointment.patient_id == user.id)
    if status:
        q = q.where(Appointment.status == status)
    rows = (await db.execute(q.order_by(Appointment.created_at.desc()).limit(300))).scalars().all()
    rows.sort(key=lambda a: (not (a.red_flag and a.status == "requested"),))          # stable: urgent open requests first
    return [await _out(a, user, db) for a in rows]


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(appointment_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    a = await _load(appointment_id, user, db, view=True)
    out = await _out(a, user, db)
    await db.commit()                                   # persists the access-audit row
    return out


@router.post("/appointments/{appointment_id}/notes", response_model=AppointmentOut)
async def add_note(appointment_id: str, body: NoteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    a = await _load(appointment_id, user, db)
    try:
        ms.comment(a, user, body.text, is_admin_user(user), body.internal)
    except ms.MedicalError as exc:
        _fail(exc)
    await db.commit()
    return await _out(a, user, db)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(appointment_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    a = await _load(appointment_id, user, db)
    try:
        ms.patient_cancel(db, a, user)
    except ms.MedicalError as exc:
        _fail(exc)
    await db.commit()
    return await _out(a, user, db)


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentOut)
async def set_status(appointment_id: str, body: StatusBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    a = await _load(appointment_id, admin, db)
    try:
        ms.set_status(db, a, body.status, admin, body.scheduled_for, body.clinician_name, body.note)
    except ms.MedicalError as exc:
        _fail(exc)
    await db.commit()
    return await _out(a, admin, db)


@router.post("/appointments/{appointment_id}/summarize", response_model=AppointmentOut)
async def summarize(appointment_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> AppointmentOut:
    a = await _load(appointment_id, admin, db, view=True)
    try:
        await ms.summarise_intake(db, a, admin)
    except ms.MedicalError as exc:
        _fail(exc)
    await db.commit()
    return await _out(a, admin, db)


@router.delete("/appointments/{appointment_id}", status_code=204)
async def erase(appointment_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> Response:
    a = await _load(appointment_id, admin, db)
    ms.audit(db, admin.tenant_id, admin.email or admin.id, f"erased appointment record {a.id[:8]}")
    await db.delete(a)
    await db.commit()
    return Response(status_code=204)
