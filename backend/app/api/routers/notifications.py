"""EAAWP Notifications Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.notification_service import (
    create_notification, list_notifications, mark_read, mark_all_read
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=list[dict])
async def list_ep(
    unread_only: bool = False, limit: int = 50,
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    notifications = await list_notifications(tenant_id, db, unread_only=unread_only, limit=limit)
    return [
        {"id": n.id, "severity": n.severity, "category": n.category,
         "title": n.title, "message": n.message, "is_read": n.is_read,
         "related_id": n.related_id, "related_type": n.related_type,
         "created_at": n.created_at.isoformat()}
        for n in notifications
    ]


@router.post("/{notification_id}/read", response_model=dict)
async def mark_read_ep(
    notification_id: str,
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    ok = await mark_read(notification_id, tenant_id, db)
    if not ok:
        raise HTTPException(404, "Notification not found.")
    return {"marked_read": True}


@router.post("/read-all", response_model=dict)
async def mark_all_read_ep(
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    count = await mark_all_read(tenant_id, db)
    return {"marked_read": count}
