"""
Team API (Phase J): invitations and member administration.

Administrators: invite people (the one-time link is returned ONCE), resend / revoke, change roles, deactivate / reactivate.
Anyone (no login): look up and accept an invitation with its secret token. These two public routes are rate-limited and
answer every invalid state with the same generic error.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.rate_limit import rate_limit
from app.db.invitation_models import Invitation
from app.db.models import User
from app.db.session import get_db
from app.services import team_service as ts

router = APIRouter(prefix="/api/v1/team", tags=["team"])
_pub_limit = rate_limit("invite", "login_rate_limit", "login_rate_window_seconds")


class InviteCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = "Employee"
    send_email: bool = False
    app_url: str = Field(default="", max_length=200)


class ResendBody(BaseModel):
    send_email: bool = False
    app_url: str = Field(default="", max_length=200)


class RoleBody(BaseModel):
    role: str = Field(..., max_length=64)


class AcceptBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)
    name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)


class LookupBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)


def _err(e: ts.TeamError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.message)


def _member_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "status": u.status, "is_active": u.is_active, "created_at": u.created_at}


@router.get("/meta")
async def meta(_: User = Depends(require_admin)):
    return {"roles": list(ts.ASSIGNABLE_ROLES), "invite_ttl_days": ts.INVITE_TTL_DAYS}


@router.get("/members")
async def members(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).where(User.tenant_id == admin.tenant_id).order_by(User.created_at))).scalars().all()
    return [_member_out(u) for u in rows]


@router.post("/members/{user_id}/role")
async def set_role(user_id: str, body: RoleBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        u = await ts.change_role(db, admin, user_id, body.role)
    except ts.TeamError as e:
        raise _err(e)
    await db.commit()
    return _member_out(u)


@router.post("/members/{user_id}/deactivate")
async def deactivate(user_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        u = await ts.set_active(db, admin, user_id, False)
    except ts.TeamError as e:
        raise _err(e)
    await db.commit()
    return _member_out(u)


@router.post("/members/{user_id}/reactivate")
async def reactivate(user_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        u = await ts.set_active(db, admin, user_id, True)
    except ts.TeamError as e:
        raise _err(e)
    await db.commit()
    return _member_out(u)


@router.get("/invitations")
async def list_invitations(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Invitation).where(Invitation.tenant_id == admin.tenant_id).order_by(Invitation.created_at.desc()).limit(200))).scalars().all()
    return [ts.out(i) for i in rows]


@router.post("/invitations", status_code=201)
async def invite(body: InviteCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        inv, token = await ts.create_invitation(db, admin, body.email, body.role)
    except ts.TeamError as e:
        raise _err(e)
    mail = await ts.email_invitation(db, admin, inv, token, body.app_url) if body.send_email else None
    await db.commit()
    return {**ts.out(inv), "token": token, "accept_path": f"/accept-invite?token={token}", "email_delivery": mail}


@router.post("/invitations/{inv_id}/resend")
async def resend(inv_id: str, body: ResendBody | None = None, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    body = body or ResendBody()
    try:
        inv, token = await ts.resend(db, admin, inv_id)
    except ts.TeamError as e:
        raise _err(e)
    mail = await ts.email_invitation(db, admin, inv, token, body.app_url) if body.send_email else None
    await db.commit()
    return {**ts.out(inv), "token": token, "accept_path": f"/accept-invite?token={token}", "email_delivery": mail}


@router.post("/invitations/{inv_id}/revoke")
async def revoke(inv_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        inv = await ts.revoke(db, admin, inv_id)
    except ts.TeamError as e:
        raise _err(e)
    await db.commit()
    return ts.out(inv)


# ── public (token-gated) ─────────────────────────────────────────────────────

@router.post("/invitations/lookup", dependencies=[Depends(_pub_limit)])
async def lookup(body: LookupBody, db: AsyncSession = Depends(get_db)):
    try:
        return await ts.lookup(db, body.token)
    except ts.TeamError as e:
        raise _err(e)


@router.post("/invitations/accept", status_code=201, dependencies=[Depends(_pub_limit)])
async def accept(body: AcceptBody, db: AsyncSession = Depends(get_db)):
    try:
        u = await ts.accept(db, body.token, body.name, body.password)
    except ts.TeamError as e:
        raise _err(e)
    await db.commit()
    return {"company_id": u.tenant_id, "email": u.email, "message": "Account created. You can sign in now."}
