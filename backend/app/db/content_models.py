"""
EAAWP Marketing Content Intelligence ORM Models

ContentItem — stores briefs, ideas, drafts, variants.
ContentPerformance — optional performance metrics linked to a content item.

Design: flexible JSON metadata rather than fixed CMS schema.
Tenant isolated. Never auto-publishes externally.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ContentItem(Base):
    """
    A single marketing content record.

    content_type: brief | idea | draft | variant | analysis
    status: draft | review | approved | rejected | archived
    channel: email | social_linkedin | social_twitter | blog | ad | landing_page | custom
    """
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    # Human-readable identifiers
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Core content fields
    brief_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Lineage
    campaign_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    objective_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # for variants

    # RAG sources used during generation (JSON list of safe labels)
    rag_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Analysis results / recommendations (JSON)
    analysis_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Flexible metadata
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
