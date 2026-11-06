"""
How an EAAWP request reaches the Project Manager records.

``pm_context`` opens the company's store, maps the signed-in EAAWP user to the identity Vyuham's code expects, and on a
successful write: snapshots progress, records stage transitions, saves (version-checked), delivers queued notifications
through EAAWP's notification service and commits. A failed request saves nothing.

Identity used by the ported code:
  role      "ADMIN" for EAAWP company administrators, otherwise "STAFF"
  sub       the EAAWP user id (project managers are named by user id)
  emp       the roster employee linked to this user by email, if any
  org_role  "MANAGER": being named on a project is what gives management rights, and only on that project
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import is_admin_user
from app.db.models import User
from app.projects import progress
from app.projects.store import Store, open_store, save_store

logger = logging.getLogger(__name__)


@dataclass
class PmContext:
    db: AsyncSession
    user: User
    u: Dict
    store: Store

    @property
    def actor(self) -> str:
        return self.u["name"]

    @property
    def is_admin(self) -> bool:
        return self.u["role"] == "ADMIN"


def identity(user: User, store: Store) -> Dict:
    emp = store.employee_by_email(user.email)
    return {"role": "ADMIN" if is_admin_user(user) else "STAFF", "sub": user.id, "emp": emp.id if emp else None,
            "org_role": "MANAGER", "name": user.name or user.email, "email": user.email}


async def _deliver(db: AsyncSession, tenant_id: str, store: Store) -> None:
    from app.services.notification_service import notify_admins, notify_users
    if not store.notices:
        return
    users = (await db.execute(select(User).where(User.tenant_id == tenant_id, User.is_active == True))).scalars().all()  # noqa: E712
    by_email = {(u.email or "").lower(): u for u in users}
    for n in store.notices:
        try:
            if n["admins"]:
                await notify_admins(db, tenant_id, "project_update", n["title"], n["message"])
            elif n["employee_id"]:
                emp = store.find_employee(n["employee_id"])
                target = by_email.get((emp.email or "").lower()) if emp else None
                if target:
                    await notify_users(db, tenant_id, [target], "project_update", n["title"], n["message"])
        except Exception:  # noqa: BLE001 - notifications never undo the change itself
            logger.warning("Project Manager notification failed", exc_info=True)
    store.notices.clear()


@asynccontextmanager
async def pm_context(db: AsyncSession, user: User, write: bool = False):
    async with open_store(db, user.tenant_id, write=write) as store:
        ctx = PmContext(db=db, user=user, u=identity(user, store), store=store)
        yield ctx
        if write:
            progress.snapshot_all()
            progress.record_transitions(ctx.actor)
            await save_store(db, store)
            await _deliver(db, user.tenant_id, store)
            await db.commit()


def require_admin_ctx(ctx: PmContext) -> None:
    from fastapi import HTTPException
    if not ctx.is_admin:
        raise HTTPException(403, "Only a company administrator can do this")


def assert_self_or_admin(ctx: PmContext, employee_id: Optional[str]) -> None:
    from fastapi import HTTPException
    if ctx.is_admin:
        return
    if not employee_id or ctx.u.get("emp") != employee_id:
        raise HTTPException(403, "You can only see your own record")


@asynccontextmanager
async def pm_action_context(db: AsyncSession, tenant_id: str, actor: str):
    """For an AI action a person already approved: administrator authority, recorded under the AI employee's name."""
    async with open_store(db, tenant_id, write=True) as store:
        from types import SimpleNamespace
        fake = SimpleNamespace(id=f"agent:{actor}"[:36], tenant_id=tenant_id, email="", name=actor, role="Company Admin")  # never stored
        ctx = PmContext(db=db, user=fake, u={"role": "ADMIN", "sub": fake.id, "emp": None, "org_role": "MANAGER", "name": actor, "email": ""},
                        store=store)
        yield ctx
        progress.snapshot_all()
        progress.record_transitions(actor)
        await save_store(db, store)
        await _deliver(db, tenant_id, store)
        await db.flush()
