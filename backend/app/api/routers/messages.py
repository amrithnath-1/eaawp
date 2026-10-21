"""
Internal messaging (Phase J, part 2): one-to-one messages between ACTIVE members of the same company.

Privacy: a conversation is visible only to its two participants - administrators cannot read other people's messages.
The sender comes from the JWT, never the request. Another company's users do not exist as far as this API is concerned (404).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.message_models import DirectMessage
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])
MAX_BODY = 2000
THREAD_LIMIT = 200


class SendBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=MAX_BODY)


def _clean(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s or "").strip()


def _out(m: DirectMessage, me: str) -> dict:
    return {"id": m.id, "from_me": m.sender_id == me, "body": m.body, "created_at": m.created_at, "read": m.read_at is not None}


async def _peer(db: AsyncSession, me: User, user_id: str, *, must_be_active: bool) -> User:
    q = select(User).where(User.id == user_id, User.tenant_id == me.tenant_id)
    if must_be_active:
        q = q.where(User.is_active == True)  # noqa: E712
    u = (await db.execute(q)).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="Person not found.")
    return u


@router.get("/people")
async def people(me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).where(User.tenant_id == me.tenant_id, User.is_active == True, User.id != me.id).order_by(User.name))).scalars().all()  # noqa: E712
    return [{"id": u.id, "name": u.name, "role": u.role} for u in rows]


@router.get("/unread-count")
async def unread_count(me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = (await db.execute(select(func.count()).select_from(DirectMessage).where(
        DirectMessage.tenant_id == me.tenant_id, DirectMessage.recipient_id == me.id, DirectMessage.read_at.is_(None)))).scalar_one()
    return {"unread": int(n)}


@router.get("/conversations")
async def conversations(me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    msgs = (await db.execute(select(DirectMessage).where(
        DirectMessage.tenant_id == me.tenant_id, or_(DirectMessage.sender_id == me.id, DirectMessage.recipient_id == me.id)
    ).order_by(DirectMessage.created_at.desc()).limit(1000))).scalars().all()
    last: dict[str, DirectMessage] = {}
    unread: dict[str, int] = {}
    for m in msgs:
        peer = m.recipient_id if m.sender_id == me.id else m.sender_id
        last.setdefault(peer, m)
        if m.recipient_id == me.id and m.read_at is None:
            unread[peer] = unread.get(peer, 0) + 1
    if not last:
        return []
    users = {u.id: u for u in (await db.execute(select(User).where(User.tenant_id == me.tenant_id, User.id.in_(list(last))))).scalars().all()}
    out = []
    for pid, m in last.items():
        u = users.get(pid)
        if u is None:
            continue
        out.append({"user_id": pid, "name": u.name, "active": u.is_active, "last_body": m.body[:120], "last_at": m.created_at,
                    "last_from_me": m.sender_id == me.id, "unread": unread.get(pid, 0)})
    return out


@router.get("/with/{user_id}")
async def thread(user_id: str, me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    peer = await _peer(db, me, user_id, must_be_active=False)
    pair = or_(and_(DirectMessage.sender_id == me.id, DirectMessage.recipient_id == peer.id),
               and_(DirectMessage.sender_id == peer.id, DirectMessage.recipient_id == me.id))
    msgs = (await db.execute(select(DirectMessage).where(DirectMessage.tenant_id == me.tenant_id, pair)
                             .order_by(DirectMessage.created_at.desc()).limit(THREAD_LIMIT))).scalars().all()
    await db.execute(update(DirectMessage).where(DirectMessage.tenant_id == me.tenant_id, DirectMessage.sender_id == peer.id,
                                                 DirectMessage.recipient_id == me.id, DirectMessage.read_at.is_(None))
                     .values(read_at=datetime.now(timezone.utc)))
    await db.commit()
    return {"peer": {"id": peer.id, "name": peer.name, "active": peer.is_active}, "messages": [_out(m, me.id) for m in reversed(msgs)]}


@router.post("/with/{user_id}", status_code=201)
async def send(user_id: str, body: SendBody, me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_id == me.id:
        raise HTTPException(status_code=400, detail="You cannot message yourself.")
    peer = await _peer(db, me, user_id, must_be_active=True)
    text = _clean(body.body)
    if not text:
        raise HTTPException(status_code=400, detail="Write a message first.")
    m = DirectMessage(id=str(uuid.uuid4()), tenant_id=me.tenant_id, sender_id=me.id, recipient_id=peer.id, body=text, created_at=datetime.now(timezone.utc))
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return _out(m, me.id)
