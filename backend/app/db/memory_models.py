"""
EAAWP Agent Memory Models

Persistent, bounded, tenant-scoped memory for the DMM agent.
Memory does NOT override security, permissions, or governance.
Memory is bounded (max per tenant/category), auditable, and searchable.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AgentMemory(Base):
    """
    A single agent memory entry.

    Categories: execution_history | decision | approved_action | rejected_action
              | company_preference | campaign_learning | strategy | recurring_pattern
              | admin_instruction

    Memory is tenant + role scoped. Bounded by category. Auditable.
    """
    __tablename__ = "agent_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, default="DIGITAL_MARKETING_MANAGER")

    # Whose memory this is. NULL = company-wide note curated by an administrator (visible to every user of the role).
    # Automatic conversation history ("execution_history") is ALWAYS tied to the user who produced it and is only ever
    # retrieved for that user; legacy history rows with no user are never retrieved.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Safe metadata (no credentials)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Relevance scoring for retrieval
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
