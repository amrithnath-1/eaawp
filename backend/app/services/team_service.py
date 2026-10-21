"""
Team management (Phase J): invitations and member administration.

Enforced here, not in the UI:
  * the invitation token is random, shown ONCE and stored only as a SHA-256; it expires and is single-use;
  * a lookup/accept of an unknown, expired, revoked or used token all give the SAME generic error;
  * only the roles in ASSIGNABLE_ROLES can be granted ("superadmin" never); people holding other roles cannot be edited here;
  * an administrator cannot change their own role or deactivate themselves (so a company always keeps an administrator);
  * deactivating a member revokes every refresh token they hold;
  * every change is written to the audit log.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, revoke_all_user_refresh_tokens
from app.db.invitation_models import Invitation
from app.db.models import AuditLog, Company, User

ASSIGNABLE_ROLES = ("Employee", "Manager", "Company Admin", "AI Administrator")
INVITE_TTL_DAYS = 7
MAX_PENDING = 50
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
INVALID = "This invitation is invalid or has expired."


class TeamError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def norm_email(e: str) -> str:
    e = (e or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 255:
        raise TeamError("Enter a valid email address.")
    return e


def check_password(pw: str, email: str) -> None:
    if len(pw or "") < 8:
        raise TeamError("Password must be at least 8 characters.")
    if len(pw) > 128:
        raise TeamError("Password is too long.")
    if pw.strip().lower() == email.lower():
        raise TeamError("Password must not be your email address.")


def audit(db: AsyncSession, tenant_id: str, actor: str, event: str) -> None:
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=tenant_id, actor=str(actor)[:64], event=event[:500], department="team", status="ok"))


def out(i: Invitation) -> dict:
    expired = i.status == "pending" and _aware(i.expires_at) <= _now()
    return {"id": i.id, "email": i.email, "role": i.role, "status": "expired" if expired else i.status,
            "invited_by_name": i.invited_by_name, "expires_at": i.expires_at, "created_at": i.created_at, "accepted_at": i.accepted_at}


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def _email_taken(db: AsyncSession, tenant_id: str, email: str) -> bool:
    return (await db.execute(select(User.id).where(User.tenant_id == tenant_id, func.lower(User.email) == email))).first() is not None


async def create_invitation(db: AsyncSession, admin: User, email: str, role: str) -> tuple[Invitation, str]:
    email = norm_email(email)
    if role not in ASSIGNABLE_ROLES:
        raise TeamError(f"Role must be one of: {', '.join(ASSIGNABLE_ROLES)}.")
    if await _email_taken(db, admin.tenant_id, email):
        raise TeamError("That person already has an account in this company.", 409)
    rows = (await db.execute(select(Invitation).where(Invitation.tenant_id == admin.tenant_id, Invitation.status == "pending"))).scalars().all()
    live = [r for r in rows if _aware(r.expires_at) > _now()]
    if any(r.email == email for r in live):
        raise TeamError("There is already a pending invitation for that email. Resend or revoke it.", 409)
    if len(live) >= MAX_PENDING:
        raise TeamError(f"Too many pending invitations ({MAX_PENDING}). Revoke some first.", 429)
    token = _new_token()
    inv = Invitation(id=str(uuid.uuid4()), tenant_id=admin.tenant_id, email=email, role=role, token_hash=hash_token(token),
                     invited_by=admin.id, invited_by_name=(admin.name or admin.email)[:255], expires_at=_now() + timedelta(days=INVITE_TTL_DAYS))
    db.add(inv)
    audit(db, admin.tenant_id, admin.id, f"invited {email} as {role}")
    await db.flush()
    return inv, token


async def get_invitation(db: AsyncSession, tenant_id: str, inv_id: str) -> Invitation:
    inv = (await db.execute(select(Invitation).where(Invitation.id == inv_id, Invitation.tenant_id == tenant_id))).scalar_one_or_none()
    if inv is None:
        raise TeamError("Invitation not found.", 404)
    return inv


async def resend(db: AsyncSession, admin: User, inv_id: str) -> tuple[Invitation, str]:
    inv = await get_invitation(db, admin.tenant_id, inv_id)
    if inv.status != "pending":
        raise TeamError(f"This invitation was {inv.status}; create a new one.", 409)
    if await _email_taken(db, admin.tenant_id, inv.email):
        raise TeamError("That person already has an account in this company.", 409)
    token = _new_token()
    inv.token_hash = hash_token(token)          # the previous link stops working
    inv.expires_at = _now() + timedelta(days=INVITE_TTL_DAYS)
    audit(db, admin.tenant_id, admin.id, f"re-issued invitation for {inv.email}")
    await db.flush()
    return inv, token


async def revoke(db: AsyncSession, admin: User, inv_id: str) -> Invitation:
    inv = await get_invitation(db, admin.tenant_id, inv_id)
    if inv.status != "pending":
        raise TeamError(f"This invitation is already {inv.status}.", 409)
    inv.status = "revoked"
    audit(db, admin.tenant_id, admin.id, f"revoked invitation for {inv.email}")
    await db.flush()
    return inv


async def _valid_by_token(db: AsyncSession, token: str) -> Invitation:
    if not token or len(token) > 200:
        raise TeamError(INVALID, 404)
    inv = (await db.execute(select(Invitation).where(Invitation.token_hash == hash_token(token)))).scalar_one_or_none()
    if inv is None or inv.status != "pending" or _aware(inv.expires_at) <= _now():
        raise TeamError(INVALID, 404)
    return inv


async def lookup(db: AsyncSession, token: str) -> dict:
    inv = await _valid_by_token(db, token)
    company = (await db.execute(select(Company).where(Company.id == inv.tenant_id))).scalar_one_or_none()
    return {"company_id": inv.tenant_id, "company_name": company.name if company else "", "email": inv.email, "role": inv.role}


async def accept(db: AsyncSession, token: str, name: str, password: str) -> User:
    inv = await _valid_by_token(db, token)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()[:120]
    if not name:
        raise TeamError("Enter your name.")
    check_password(password, inv.email)
    if await _email_taken(db, inv.tenant_id, inv.email):
        raise TeamError(INVALID, 404)
    inv.status = "accepted"
    inv.accepted_at = _now()
    user = User(id=str(uuid.uuid4()), tenant_id=inv.tenant_id, email=inv.email, name=name, hashed_password=hash_password(password),
                role=inv.role if inv.role in ASSIGNABLE_ROLES else "Employee", status="Active", is_active=True)
    db.add(user)
    audit(db, inv.tenant_id, user.id, f"{inv.email} accepted invitation as {user.role}")
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise TeamError(INVALID, 404)
    return user


# ── members ───────────────────────────────────────────────────────────────────

async def _member(db: AsyncSession, admin: User, user_id: str) -> User:
    u = (await db.execute(select(User).where(User.id == user_id, User.tenant_id == admin.tenant_id))).scalar_one_or_none()
    if u is None:
        raise TeamError("Member not found.", 404)
    return u


async def change_role(db: AsyncSession, admin: User, user_id: str, role: str) -> User:
    u = await _member(db, admin, user_id)
    if u.id == admin.id:
        raise TeamError("You cannot change your own role.", 403)
    if role not in ASSIGNABLE_ROLES:
        raise TeamError(f"Role must be one of: {', '.join(ASSIGNABLE_ROLES)}.")
    if u.role not in ASSIGNABLE_ROLES:
        raise TeamError("This account cannot be changed here.", 403)
    old, u.role = u.role, role
    audit(db, admin.tenant_id, admin.id, f"role of {u.email}: {old} -> {role}")
    await db.flush()
    return u


async def set_active(db: AsyncSession, admin: User, user_id: str, active: bool) -> User:
    u = await _member(db, admin, user_id)
    if u.id == admin.id:
        raise TeamError("You cannot deactivate your own account.", 403)
    if u.role not in ASSIGNABLE_ROLES:
        raise TeamError("This account cannot be changed here.", 403)
    u.is_active, u.status = active, ("Active" if active else "Deactivated")
    if not active:
        await revoke_all_user_refresh_tokens(u.id, db)
    audit(db, admin.tenant_id, admin.id, f"{'reactivated' if active else 'deactivated'} {u.email}")
    await db.flush()
    return u
