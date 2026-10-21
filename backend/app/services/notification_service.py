"""
EAAWP notifications (Phase M).

* One row per RECIPIENT. Events for administrators (approvals, failed workflows, monitoring alerts, new members) fan out to the
  company's active administrators only; employees never see them.
* Email is double opt-in: (1) an administrator authorized automatic notification emails for the company
  (NotificationSettings, default OFF) AND (2) the recipient switched email on for that category (default OFF).
  Both are checked when the notification is created AND again at delivery time (the outbox), so turning the company switch or
  a personal preference off stops mail that is still queued.
* Email content is a fixed generic template (category + a link to the app): never the notification's message, so no company data
  travels over email. Sent through the company's own SMTP integration; capped per hour; every attempt is written to EmailAuditLog.
* Creating a notification must never break the action that caused it: callers use notify_admins/notify_user, which swallow errors.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.notification_models import Notification, NotificationPreference, NotificationSettings

logger = logging.getLogger(__name__)

MAX_LIMIT = 200
EMAIL_ROLE_KEY = "notification"
EMAIL_HOURLY_CAP = 50
EMAIL_MAX_ATTEMPTS = 3
EMAIL_BATCH = 50

# category -> (label, admin_only, email_allowed). Email is only ever allowed for categories whose existence is not sensitive.
CATEGORIES: dict[str, tuple[str, bool, bool]] = {
    "approval_requested": ("An action is waiting for your approval", True, True),
    "workflow_failed": ("A workflow run failed", True, True),
    "monitoring_alert": ("A monitoring rule was triggered", True, True),
    "member_joined": ("A new member joined the company", True, True),
}
ADMIN_ROLES = frozenset({"admin", "superadmin", "company admin", "ai administrator"})
SEVERITIES = ("info", "warning", "critical")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_admin_role(role: str | None) -> bool:
    return (role or "").lower() in ADMIN_ROLES


def categories_for(role: str | None) -> list[str]:
    admin = is_admin_role(role)
    return [k for k, (_l, admin_only, _e) in CATEGORIES.items() if admin or not admin_only]


# ── Settings / preferences ────────────────────────────────────────────────────

async def company_email_enabled(tenant_id: str, db: AsyncSession) -> bool:
    row = (await db.execute(select(NotificationSettings).where(NotificationSettings.tenant_id == tenant_id))).scalar_one_or_none()
    return bool(row and row.email_enabled)


async def set_company_email_enabled(tenant_id: str, enabled: bool, changed_by: str, db: AsyncSession) -> None:
    row = (await db.execute(select(NotificationSettings).where(NotificationSettings.tenant_id == tenant_id))).scalar_one_or_none()
    if row is None:
        db.add(NotificationSettings(tenant_id=tenant_id, email_enabled=enabled, changed_by=str(changed_by)[:64]))
    else:
        row.email_enabled = enabled
        row.changed_by = str(changed_by)[:64]
        row.changed_at = _now()
    await db.flush()


async def get_preferences(tenant_id: str, user_id: str, db: AsyncSession) -> dict[str, tuple[bool, bool]]:
    rows = (await db.execute(select(NotificationPreference).where(
        NotificationPreference.tenant_id == tenant_id, NotificationPreference.user_id == user_id))).scalars().all()
    return {r.category: (bool(r.in_app), bool(r.email)) for r in rows}


async def set_preference(tenant_id: str, user_id: str, category: str, in_app: bool, email: bool, db: AsyncSession) -> None:
    row = (await db.execute(select(NotificationPreference).where(
        NotificationPreference.tenant_id == tenant_id, NotificationPreference.user_id == user_id,
        NotificationPreference.category == category))).scalar_one_or_none()
    if row is None:
        db.add(NotificationPreference(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, category=category,
                                      in_app=in_app, email=email))
    else:
        row.in_app, row.email, row.changed_at = in_app, email, _now()
    await db.flush()


# ── Creating notifications ────────────────────────────────────────────────────

async def _deliver_to(db: AsyncSession, tenant_id: str, user, category: str, title: str, message: str, severity: str,
                      related_id: str | None, related_type: str | None, company_email: bool) -> Notification | None:
    prefs = await get_preferences(tenant_id, user.id, db)
    in_app, want_email = prefs.get(category, (True, False))
    label, _admin_only, email_allowed = CATEGORIES.get(category, ("", False, False))
    email_status = "pending" if (company_email and want_email and email_allowed) else "none"
    if not in_app and email_status == "none":
        return None
    n = Notification(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user.id,
                     severity=severity if severity in SEVERITIES else "info", category=category[:64],
                     title=title[:255], message=message[:2000], related_id=related_id, related_type=related_type,
                     is_read=not in_app, email_status=email_status)
    db.add(n)
    return n


async def notify_users(db: AsyncSession, tenant_id: str, users: list, category: str, title: str, message: str = "",
                       severity: str = "info", related_id: str | None = None, related_type: str | None = None) -> int:
    """Create one notification per recipient (own SAVEPOINT: a failure here never breaks the caller). Returns the count created."""
    try:
        async with db.begin_nested():
            company_email = await company_email_enabled(tenant_id, db)
            made = 0
            for u in users:
                if await _deliver_to(db, tenant_id, u, category, title, message, severity, related_id, related_type, company_email):
                    made += 1
            await db.flush()
            return made
    except Exception:  # noqa: BLE001 - notifications are best-effort
        logger.warning("notification fan-out failed for tenant %s category %s", tenant_id, category, exc_info=True)
        return 0


async def notify_admins(db: AsyncSession, tenant_id: str, category: str, title: str, message: str = "", severity: str = "info",
                        related_id: str | None = None, related_type: str | None = None, exclude_user_id: str | None = None) -> int:
    from app.db.models import User
    try:
        admins_q = select(User).where(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
        admins = [u for u in (await db.execute(admins_q)).scalars().all()
                  if is_admin_role(u.role) and u.id != exclude_user_id]
    except Exception:  # noqa: BLE001
        logger.warning("could not list administrators for tenant %s", tenant_id, exc_info=True)
        return 0
    return await notify_users(db, tenant_id, admins, category, title, message, severity, related_id, related_type)


async def create_notification(
    tenant_id: str, title: str, message: str, db: AsyncSession,
    severity: str = "info", category: str = "agent_decision",
    related_id: str | None = None, related_type: str | None = None,
) -> Notification:
    """Company-wide notice with no addressee (user_id NULL): visible to administrators only, never emailed.
    Prefer notify_admins / notify_users, which honour each person's preferences and consent."""
    n = Notification(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=None,
                     severity=severity if severity in SEVERITIES else "info", category=category[:64],
                     title=title[:255], message=message[:2000], related_id=related_id, related_type=related_type)
    db.add(n)
    await db.flush()
    return n


# ── Reading (always the caller's OWN notifications) ───────────────────────────

def _mine(tenant_id: str, user_id: str, is_admin: bool):
    """Own rows; legacy company-wide rows (user_id NULL) only for administrators."""
    from sqlalchemy import or_
    cond = Notification.user_id == user_id
    if is_admin:
        cond = or_(cond, Notification.user_id.is_(None))
    return Notification.tenant_id == tenant_id, cond


async def list_for_user(tenant_id: str, user_id: str, is_admin: bool, db: AsyncSession, unread_only: bool = False,
                        limit: int = 50) -> list[Notification]:
    stmt = select(Notification).where(*_mine(tenant_id, user_id, is_admin))
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id).limit(max(1, min(limit, MAX_LIMIT)))
    return list((await db.execute(stmt)).scalars().all())


async def unread_count(tenant_id: str, user_id: str, is_admin: bool, db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Notification).where(*_mine(tenant_id, user_id, is_admin), Notification.is_read == False)  # noqa: E712
    return int((await db.execute(stmt)).scalar_one())


async def mark_read(notification_id: str, tenant_id: str, user_id: str, is_admin: bool, db: AsyncSession) -> bool:
    stmt = select(Notification).where(Notification.id == notification_id, *_mine(tenant_id, user_id, is_admin))
    n = (await db.execute(stmt)).scalar_one_or_none()
    if n is None:
        return False
    n.is_read = True
    await db.flush()
    return True


async def mark_all_read(tenant_id: str, user_id: str, is_admin: bool, db: AsyncSession) -> int:
    stmt = select(Notification).where(*_mine(tenant_id, user_id, is_admin), Notification.is_read == False)  # noqa: E712
    rows = (await db.execute(stmt)).scalars().all()
    for n in rows:
        n.is_read = True
    await db.flush()
    return len(rows)


# ── Email outbox ──────────────────────────────────────────────────────────────

def _app_url() -> str | None:
    from app.config import settings
    origins = [o for o in settings.cors_origins_list if o.startswith(("http://", "https://")) and "*" not in o]
    return origins[0].rstrip("/") if origins else None


async def deliver_pending_emails(db: AsyncSession, limit: int = EMAIL_BATCH) -> dict:
    """Send queued notification emails. Re-checks consent for EVERY message. Never raises. Returns counts."""
    from app.db.email_models import EmailAuditLog
    from app.db.models import Company, User
    from app.integrations import email_provider as ep

    counts = {"sent": 0, "failed": 0, "skipped": 0, "deferred": 0}
    pending_q = (select(Notification).where(Notification.email_status == "pending")
                 .order_by(Notification.created_at, Notification.id).limit(limit))
    pending = list((await db.execute(pending_q)).scalars().all())
    providers: dict[str, object] = {}
    for n in pending:
        t = n.tenant_id
        user = (await db.execute(select(User).where(User.id == n.user_id, User.tenant_id == t))).scalar_one_or_none() if n.user_id else None
        prefs = await get_preferences(t, n.user_id, db) if n.user_id else {}
        consent = (user is not None and user.is_active and bool(user.email) and await company_email_enabled(t, db)
                   and prefs.get(n.category, (True, False))[1] and CATEGORIES.get(n.category, ("", False, False))[2]
                   and (is_admin_role(user.role) or not CATEGORIES[n.category][1]))
        if not consent:
            n.email_status, counts["skipped"] = "skipped", counts["skipped"] + 1
            continue
        recent = (await db.execute(select(func.count()).select_from(EmailAuditLog).where(
            EmailAuditLog.tenant_id == t, EmailAuditLog.role_key == EMAIL_ROLE_KEY,
            EmailAuditLog.attempted_at >= _now() - timedelta(hours=1)))).scalar_one()
        if int(recent) >= EMAIL_HOURLY_CAP:          # this run's own audit rows are autoflushed, so they count
            counts["deferred"] += 1          # stays pending; retried on a later tick
            continue
        if t not in providers:
            providers[t] = await ep.get_email_provider(t, db)
        provider = providers[t]
        if provider is None:
            n.email_status, counts["skipped"] = "skipped", counts["skipped"] + 1
            continue
        company = (await db.execute(select(Company).where(Company.id == t))).scalar_one_or_none()
        cname = " ".join((company.name if company else "your company").split())[:80]
        label = CATEGORIES[n.category][0]
        base = _app_url()
        subject = f"[{cname}] {label}"
        body = (f"Hello,\n\n{label} in {cname}.\n\n"
                + (f"Open the app to see the details: {base}\n\n" if base else "Open the app to see the details.\n\n")
                + "You are receiving this because an administrator enabled notification emails for your company and you "
                  "turned them on for this type of event. You can turn them off any time in Settings > Notifications.")
        try:
            result = await provider.send([user.email], subject, body)
        except Exception:  # noqa: BLE001 - never echo transport exception text
            result = ep.SendResult(success=False, error_message="The email service failed unexpectedly.")
        n.email_attempts = (n.email_attempts or 0) + 1
        db.add(EmailAuditLog(id=str(uuid.uuid4()), tenant_id=t, role_key=EMAIL_ROLE_KEY, recipient_count=1,
                             recipient_domains=user.email.split("@")[-1][:200], subject_length=len(subject), body_length=len(body),
                             success=bool(result.success), provider_message_id=(result.message_id or None),
                             error_message=None if result.success else (result.error_message or "send failed")[:500]))
        if result.success:
            n.email_status, counts["sent"] = "sent", counts["sent"] + 1
        elif n.email_attempts >= EMAIL_MAX_ATTEMPTS:
            n.email_status, counts["failed"] = "failed", counts["failed"] + 1
        else:
            counts["deferred"] += 1
    await db.flush()
    return counts
