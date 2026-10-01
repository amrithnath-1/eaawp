"""EAAWP Notification Service — tenant-scoped, bounded."""
from __future__ import annotations
import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.notification_models import Notification

logger = logging.getLogger(__name__)
MAX_UNREAD_PER_TENANT = 200


async def create_notification(
    tenant_id: str, title: str, message: str, db: AsyncSession,
    severity: str = "info", category: str = "agent_decision",
    related_id: str | None = None, related_type: str | None = None,
) -> Notification:
    n = Notification(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        severity=severity, category=category,
        title=title, message=message,
        related_id=related_id, related_type=related_type,
    )
    db.add(n)
    await db.flush()
    return n


async def list_notifications(
    tenant_id: str, db: AsyncSession,
    unread_only: bool = False, limit: int = 50,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.tenant_id == tenant_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712
    stmt = stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_read(notification_id: str, tenant_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
        )
    )
    n = result.scalar_one_or_none()
    if not n:
        return False
    n.is_read = True
    await db.flush()
    return True


async def mark_all_read(tenant_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    notifications = result.scalars().all()
    for n in notifications:
        n.is_read = True
    await db.flush()
    return len(notifications)
