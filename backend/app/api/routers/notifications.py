"""EAAWP Notifications Router (Phase M): each person sees only their own notifications; email needs company authorization + opt-in."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.services import notification_service as ns

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _out(n) -> dict:
    return {"id": n.id, "severity": n.severity, "category": n.category, "title": n.title, "message": n.message,
            "is_read": n.is_read, "related_id": n.related_id, "related_type": n.related_type,
            "created_at": n.created_at.isoformat() if n.created_at else None}


@router.get("", response_model=list[dict])
async def list_ep(unread_only: bool = False, limit: int = Query(default=50, ge=1, le=ns.MAX_LIMIT),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await ns.list_for_user(user.tenant_id, user.id, ns.is_admin_role(user.role), db, unread_only=unread_only, limit=limit)
    return [_out(n) for n in rows]


@router.get("/unread-count", response_model=dict)
async def unread_ep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"unread": await ns.unread_count(user.tenant_id, user.id, ns.is_admin_role(user.role), db)}


@router.post("/read-all", response_model=dict)
async def mark_all_read_ep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"marked_read": await ns.mark_all_read(user.tenant_id, user.id, ns.is_admin_role(user.role), db)}


@router.post("/{notification_id}/read", response_model=dict)
async def mark_read_ep(notification_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if not await ns.mark_read(notification_id, user.tenant_id, user.id, ns.is_admin_role(user.role), db):
        raise HTTPException(404, "Notification not found.")
    return {"marked_read": True}


# ── Preferences (own) and company authorization (admin) ───────────────────────

async def _provider_ready(tenant_id: str, db: AsyncSession) -> bool:
    from app.integrations.email_provider import get_email_provider
    return (await get_email_provider(tenant_id, db)) is not None


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    in_app: bool = True
    email: bool = False


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_enabled: bool


@router.get("/preferences", response_model=dict)
async def get_prefs_ep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    prefs = await ns.get_preferences(user.tenant_id, user.id, db)
    company_on = await ns.company_email_enabled(user.tenant_id, db)
    items = []
    for key in ns.categories_for(user.role):
        label, _admin_only, email_allowed = ns.CATEGORIES[key]
        in_app, email = prefs.get(key, (True, False))
        items.append({"category": key, "label": label, "in_app": in_app, "email": email and email_allowed,
                      "email_available": email_allowed})
    return {"categories": items, "company_email_enabled": company_on,
            "email_will_be_sent": company_on and any(i["email"] for i in items)}


@router.put("/preferences", response_model=dict)
async def put_pref_ep(body: PreferenceIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if body.category not in ns.categories_for(user.role):
        raise HTTPException(404, "Unknown notification type.")
    if body.email and not ns.CATEGORIES[body.category][2]:
        raise HTTPException(400, "Email is not available for this type of notification.")
    await ns.set_preference(user.tenant_id, user.id, body.category, body.in_app, body.email, db)
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=user.tenant_id, actor=str(user.id)[:64], department="notifications", status="ok",
                    event=f"notification preference {body.category}: in_app={'on' if body.in_app else 'off'}, email={'on' if body.email else 'off'}"))
    return {"category": body.category, "in_app": body.in_app, "email": body.email}


@router.get("/settings", response_model=dict, dependencies=[Depends(require_admin)])
async def get_settings_ep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"email_enabled": await ns.company_email_enabled(user.tenant_id, db),
            "email_provider_ready": await _provider_ready(user.tenant_id, db),
            "hourly_cap": ns.EMAIL_HOURLY_CAP}


@router.put("/settings", response_model=dict, dependencies=[Depends(require_admin)])
async def put_settings_ep(body: SettingsIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    ready = await _provider_ready(user.tenant_id, db)
    if body.email_enabled and not ready:
        raise HTTPException(400, "Set up and enable the company's email connection first (Integrations), then authorize notification emails.")
    await ns.set_company_email_enabled(user.tenant_id, body.email_enabled, user.id, db)
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=user.tenant_id, actor=str(user.id)[:64], department="notifications", status="ok",
                    event=f"automatic notification emails {'authorized' if body.email_enabled else 'switched off'} for the company"))
    return {"email_enabled": body.email_enabled, "email_provider_ready": ready, "hourly_cap": ns.EMAIL_HOURLY_CAP}
