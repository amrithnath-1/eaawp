"""EAAWP Agent Memory Router.

Company-wide memory is curated by administrators only: every user's agent reads it, so a note written here steers every
conversation. Members can search only what they may see (company-wide notes plus their own history)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.services import memory_service as ms

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
DEFAULT_ROLE = "DIGITAL_MARKETING_MANAGER"


class MemoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = DEFAULT_ROLE
    category: str = "company_preference"
    title: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=5000)
    metadata: dict | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


def _role(value: str) -> str:
    if not ms.ROLE_KEY_RE.match(value or ""):
        raise HTTPException(422, "Role key must be upper-case letters, digits and underscores.")
    return value


def _audit(db: AsyncSession, user: User, event: str) -> None:
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=user.tenant_id, actor=str(user.id)[:64], department="memory", status="ok", event=event[:500]))


@router.post("", response_model=dict, status_code=201, dependencies=[Depends(require_admin)])
async def create_memory(body: MemoryIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if body.category not in ms.VALID_CATEGORIES or body.category == ms.HISTORY:
        raise HTTPException(422, "Choose a company memory category (conversation history is saved automatically, per person).")
    if not body.title.strip() and not body.content.strip():
        raise HTTPException(422, "Enter a title or some content.")
    role = _role(body.role_key)
    mem = await ms.store_memory(tenant_id=user.tenant_id, role_key=role, category=body.category, title=body.title.strip(),
                                content=body.content.strip(), db=db, metadata=body.metadata, confidence=body.confidence, user_id=None)
    _audit(db, user, f"company memory added ({role}/{body.category})")
    return {"id": mem.id, "category": mem.category, "title": mem.title}


@router.get("", response_model=list[dict], dependencies=[Depends(require_admin)])
async def list_memory(role_key: str | None = None, limit: int = Query(default=100, ge=1, le=500),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await ms.list_memories(user.tenant_id, db, _role(role_key) if role_key else None, limit)
    return [{"id": m.id, "role_key": m.role_key, "category": m.category, "title": m.title, "content": m.content[:500],
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in rows]


@router.delete("/{memory_id}", response_model=dict, dependencies=[Depends(require_admin)])
async def delete_memory(memory_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    if not await ms.delete_memory(user.tenant_id, memory_id, db):
        raise HTTPException(404, "Memory note not found.")
    _audit(db, user, "company memory removed")
    return {"removed": True}


@router.get("/search", response_model=list[dict])
async def search_memories(
    q: str = Query(min_length=1, max_length=200), category: str | None = None, role_key: str = DEFAULT_ROLE,
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await ms.search_memory(
        tenant_id=user.tenant_id, role_key=_role(role_key), query=q, db=db,
        categories=[category] if category else None, limit=limit, user_id=user.id,
    )
