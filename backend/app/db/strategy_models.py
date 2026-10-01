"""
EAAWP Marketing Strategy ORM Models

MarketingObjective — tenant-scoped strategic objective.
No hardcoded business-model assumptions.
Tenant isolation enforced on every query.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class MarketingObjective(Base):
    """
    A tenant-owned marketing objective.

    Supported types (not enforced as enum — extensible):
        lead_generation | conversion | revenue | customer_acquisition
        campaign_efficiency | brand_awareness | custom

    Status lifecycle: draft → active → achieved → paused → cancelled
    """
    __tablename__ = "marketing_objectives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objective_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # 1=critical…5=low
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    target_metric: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # JSON list of linked campaign IDs
    linked_campaign_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
