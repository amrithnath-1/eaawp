"""EAAWP Agent Memory Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.memory_service import store_memory, search_memory, VALID_CATEGORIES

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


@router.post("", response_model=dict, status_code=201)
async def create_memory(body: dict, tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    mem = await store_memory(
        tenant_id=tenant_id,
        role_key=body.get("role_key", "DIGITAL_MARKETING_MANAGER"),
        category=body.get("category", "execution_history"),
        title=body.get("title", "")[:255],
        content=body.get("content", "")[:5000],
        db=db,
        metadata=body.get("metadata"),
        confidence=float(body.get("confidence", 1.0)),
    )
    return {"id": mem.id, "category": mem.category, "title": mem.title}


@router.get("/search", response_model=list[dict])
async def search_memories(
    q: str, category: str | None = None, limit: int = 10,
    tenant_id: str = Depends(get_current_tenant_id), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    categories = [category] if category else None
    return await search_memory(
        tenant_id=tenant_id,
        role_key="DIGITAL_MARKETING_MANAGER",
        query=q, db=db, categories=categories, limit=limit,
    )
