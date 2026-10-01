"""
EAAWP Agent Memory Service

Bounded, searchable, tenant-scoped memory for the DMM.
Max 100 entries per category per tenant. Auto-archives least-relevant.
Memory NEVER overrides security, permissions, or governance.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.memory_models import AgentMemory

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "execution_history", "decision", "approved_action", "rejected_action",
    "company_preference", "campaign_learning", "strategy", "recurring_pattern",
    "admin_instruction",
}
MAX_PER_CATEGORY = 100


async def store_memory(
    tenant_id: str, role_key: str, category: str,
    title: str, content: str, db: AsyncSession,
    metadata: dict[str, Any] | None = None,
    confidence: float = 1.0,
) -> AgentMemory:
    if category not in VALID_CATEGORIES:
        category = "execution_history"
    # Enforce bound — archive oldest if at limit
    count_result = await db.execute(
        select(func.count(AgentMemory.id)).where(
            AgentMemory.tenant_id == tenant_id,
            AgentMemory.role_key == role_key,
            AgentMemory.category == category,
            AgentMemory.is_active == True,  # noqa: E712
        )
    )
    count = count_result.scalar() or 0
    if count >= MAX_PER_CATEGORY:
        # Archive oldest
        oldest_result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.tenant_id == tenant_id,
                AgentMemory.role_key == role_key,
                AgentMemory.category == category,
                AgentMemory.is_active == True,  # noqa: E712
            ).order_by(AgentMemory.relevance_score.asc(), AgentMemory.created_at.asc()).limit(5)
        )
        for old in oldest_result.scalars().all():
            old.is_active = False

    mem = AgentMemory(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id, role_key=role_key,
        category=category, title=title, content=content,
        metadata_json=json.dumps(metadata or {}),
        confidence=confidence,
    )
    db.add(mem)
    await db.flush()
    return mem


async def search_memory(
    tenant_id: str, role_key: str, query: str, db: AsyncSession,
    categories: list[str] | None = None, limit: int = 10,
) -> list[dict[str, Any]]:
    """Simple keyword-based memory search. Returns safe dicts."""
    stmt = select(AgentMemory).where(
        AgentMemory.tenant_id == tenant_id,
        AgentMemory.role_key == role_key,
        AgentMemory.is_active == True,  # noqa: E712
    )
    if categories:
        stmt = stmt.where(AgentMemory.category.in_(categories))
    stmt = stmt.order_by(AgentMemory.relevance_score.desc(), AgentMemory.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    all_mems = result.scalars().all()

    # Simple relevance: count query word matches
    q_words = set(query.lower().split())
    scored = []
    for m in all_mems:
        text = (m.title + " " + m.content).lower()
        score = sum(1 for w in q_words if w in text)
        if score > 0:
            scored.append((score, m))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Update access count for returned memories
    now = datetime.now(timezone.utc)
    results = []
    for _, m in scored[:limit]:
        m.access_count += 1
        m.last_accessed_at = now
        results.append({
            "id": m.id, "category": m.category, "title": m.title,
            "content": m.content[:500], "confidence": m.confidence,
            "created_at": m.created_at.isoformat(),
        })
    if results:
        await db.flush()
    return results
