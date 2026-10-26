"""
Conversation history (History tab): the signed-in person's own AI employee conversations.

GET    /api/v1/conversations                 list own conversations (newest first; filter by role, search, page)
GET    /api/v1/conversations/{id}            messages of one own conversation (latest page; `before` for older)
PATCH  /api/v1/conversations/{id}            rename
DELETE /api/v1/conversations/{id}            delete

There is no endpoint that reads another person's conversations, for administrators either.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import conversations as cs
from app.services.workspaces import get_workspace

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class RenameIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


def _role_name(key: str) -> str:
    w = get_workspace(key)
    return w.name if w else key.replace("_", " ").title()


@router.get("")
async def list_conversations(
    role_key: str | None = Query(default=None, max_length=128),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    before: datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = await cs.list_conversations(db, user, role_key, q, limit, before)
    for i in items:
        i["role_name"] = _role_name(i["role_key"])
    return {"items": items, "has_more": len(items) == limit}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    limit: int = Query(default=60, ge=1, le=cs.PAGE_SIZE_MAX),
    before: datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conv = await cs.get_owned(db, user, conversation_id)
    messages, has_more = await cs.get_messages(db, conv, limit, before)
    return {"id": conv.id, "title": conv.title, "role_key": conv.role_key, "role_name": _role_name(conv.role_key),
            "created_at": conv.created_at, "updated_at": conv.updated_at, "messages": messages, "has_more": has_more}


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: str, body: RenameIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conv = await cs.get_owned(db, user, conversation_id)
    await cs.rename(db, conv, body.title)
    return {"id": conv.id, "title": conv.title}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    conv = await cs.get_owned(db, user, conversation_id)
    await cs.remove(db, conv)
