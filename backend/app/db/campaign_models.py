"""
EAAWP Campaign Domain Models

These are EAAWP-internal campaign workspace records belonging to the tenant.
They are entirely separate from any external company database.

Data separation principle
--------------------------
These models represent the DMM's own structured campaign workspace.
External company data (leads, revenue, ad spend, etc.) lives in the
customer's external database and is accessed only through the existing
controlled data-access layer (semantic mappings / query_company_data).
This model NEVER assumes external table names or column schemas.

Tenant isolation: every row carries tenant_id. All queries MUST filter by it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Campaign ──────────────────────────────────────────────────────────────────

class Campaign(Base):
    """
    An EAAWP-internal marketing campaign record for the DMM.

    Status lifecycle:
        draft → planned → active → paused → completed
                                          → cancelled
        draft → cancelled (discarded early)

    JSON fields allow flexible configuration without schema migrations.
    """

    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Status
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", index=True
    )  # draft | planned | active | paused | completed | cancelled

    # Targeting & channel (flexible text — not a hardcoded enum)
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # Budget — stored as float; currency assumed to match tenant's locale
    budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Dates — stored as ISO strings for flexibility (no timezone issues with SQLite)
    start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # KPI definitions — JSON list of {name, target, unit}
    kpis_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Flexible metadata — JSON dict for future-proofing
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Audit
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── CampaignMetric ────────────────────────────────────────────────────────────

class CampaignMetric(Base):
    """
    A metric data point recorded for a campaign.

    Metrics can come from:
    - manual input by the DMM/agent
    - external company data retrieved via query_company_data

    The source field distinguishes the origin.
    Flexible metadata_json allows storing context without schema changes.

    Security: never stores credentials, raw SQL, or chain-of-thought.
    """

    __tablename__ = "campaign_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metric_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    # Where this metric came from
    source: Mapped[str] = mapped_column(
        String(128), nullable=False, default="manual"
    )  # "manual" | "query_company_data" | "monitoring" | etc.

    # Flexible context (e.g. which semantic concept was the source)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    recorded_by: Mapped[str] = mapped_column(String(128), nullable=False, default="agent")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
