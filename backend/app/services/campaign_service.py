"""
EAAWP Campaign Service

Business logic for the Campaign Management subsystem.
All operations are tenant-scoped — cross-tenant access is structurally prevented.

Security invariants
-------------------
- Every query includes tenant_id filter.
- No raw SQL accepted from callers.
- Metrics stored as structured floats — never raw query results.
- Audit metadata contains only safe summaries, no credentials.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.campaign_models import Campaign, CampaignMetric
from app.schemas.campaign import (
    CampaignCreate,
    CampaignMetricCreate,
    CampaignOut,
    CampaignMetricOut,
    CampaignSummary,
    CampaignUpdate,
    KPIDefinition,
)

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _campaign_to_out(c: Campaign) -> CampaignOut:
    kpis_raw = json.loads(c.kpis_json or "[]")
    kpis = [KPIDefinition(**k) for k in kpis_raw]
    meta = json.loads(c.metadata_json or "{}")
    return CampaignOut(
        id=c.id,
        tenant_id=c.tenant_id,
        name=c.name,
        objective=c.objective,
        description=c.description,
        status=c.status,
        target_audience=c.target_audience,
        channel=c.channel,
        budget=c.budget,
        start_date=c.start_date,
        end_date=c.end_date,
        kpis=kpis,
        metadata=meta,
        created_by=c.created_by,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _metric_to_out(m: CampaignMetric) -> CampaignMetricOut:
    meta = json.loads(m.metadata_json or "{}")
    return CampaignMetricOut(
        id=m.id,
        campaign_id=m.campaign_id,
        tenant_id=m.tenant_id,
        metric_name=m.metric_name,
        metric_value=m.metric_value,
        metric_date=m.metric_date,
        source=m.source,
        metadata=meta,
        recorded_by=m.recorded_by,
        recorded_at=m.recorded_at,
    )


# ── Campaign CRUD ─────────────────────────────────────────────────────────────

async def create_campaign(
    body: CampaignCreate,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignOut:
    campaign = Campaign(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=body.name,
        objective=body.objective,
        description=body.description,
        status="draft",
        target_audience=body.target_audience,
        channel=body.channel,
        budget=body.budget,
        start_date=body.start_date,
        end_date=body.end_date,
        kpis_json=json.dumps([k.model_dump() for k in body.kpis]),
        metadata_json=json.dumps(body.metadata),
        created_by=body.created_by,
    )
    db.add(campaign)
    await db.flush()
    logger.info("Campaign created: %s (tenant=%s)", campaign.id, tenant_id)
    return _campaign_to_out(campaign)


async def list_campaigns(
    tenant_id: str,
    db: AsyncSession,
    status: str | None = None,
    limit: int = 50,
) -> list[CampaignOut]:
    stmt = select(Campaign).where(Campaign.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Campaign.status == status)
    stmt = stmt.order_by(Campaign.created_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return [_campaign_to_out(c) for c in result.scalars().all()]


async def get_campaign(
    campaign_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignOut | None:
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    return _campaign_to_out(c) if c else None


async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignOut | None:
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return None

    if body.name is not None:
        c.name = body.name
    if body.objective is not None:
        c.objective = body.objective
    if body.description is not None:
        c.description = body.description
    if body.target_audience is not None:
        c.target_audience = body.target_audience
    if body.channel is not None:
        c.channel = body.channel
    if body.budget is not None:
        c.budget = body.budget
    if body.start_date is not None:
        c.start_date = body.start_date
    if body.end_date is not None:
        c.end_date = body.end_date
    if body.status is not None:
        c.status = body.status
    if body.kpis is not None:
        c.kpis_json = json.dumps([k.model_dump() for k in body.kpis])
    if body.metadata is not None:
        c.metadata_json = json.dumps(body.metadata)

    await db.flush()
    # ``updated_at`` is refreshed server-side (onupdate); reload it inside the
    # async context so serialising the row does not trigger a lazy load.
    await db.refresh(c)
    return _campaign_to_out(c)


async def archive_campaign(
    campaign_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignOut | None:
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return None
    c.status = "cancelled"
    await db.flush()
    await db.refresh(c)  # reload server-side ``updated_at`` inside the async context
    return _campaign_to_out(c)


# ── Campaign Metrics ──────────────────────────────────────────────────────────

async def record_metric(
    campaign_id: str,
    body: CampaignMetricCreate,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignMetricOut | None:
    # Verify campaign belongs to tenant
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        return None

    metric = CampaignMetric(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        metric_name=body.metric_name,
        metric_value=body.metric_value,
        metric_date=body.metric_date,
        source=body.source,
        metadata_json=json.dumps(body.metadata),
        recorded_by=body.recorded_by,
    )
    db.add(metric)
    await db.flush()
    return _metric_to_out(metric)


async def get_metrics(
    campaign_id: str,
    tenant_id: str,
    db: AsyncSession,
    metric_name: str | None = None,
    limit: int = 100,
) -> list[CampaignMetricOut]:
    # Verify campaign tenant
    cam_result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    if not cam_result.scalar_one_or_none():
        return []

    stmt = select(CampaignMetric).where(
        CampaignMetric.campaign_id == campaign_id,
        CampaignMetric.tenant_id == tenant_id,
    )
    if metric_name:
        stmt = stmt.where(CampaignMetric.metric_name == metric_name)
    stmt = stmt.order_by(CampaignMetric.metric_date.desc()).limit(min(limit, 500))
    result = await db.execute(stmt)
    return [_metric_to_out(m) for m in result.scalars().all()]


async def get_campaign_summary(
    campaign_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CampaignSummary | None:
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return None

    metrics_result = await db.execute(
        select(CampaignMetric)
        .where(
            CampaignMetric.campaign_id == campaign_id,
            CampaignMetric.tenant_id == tenant_id,
        )
        .order_by(CampaignMetric.recorded_at.desc())
        .limit(10)
    )
    metrics = metrics_result.scalars().all()
    kpis = json.loads(c.kpis_json or "[]")

    latest_metrics = [
        {
            "name": m.metric_name,
            "value": m.metric_value,
            "date": m.metric_date,
            "source": m.source,
        }
        for m in metrics
    ]

    return CampaignSummary(
        id=c.id,
        name=c.name,
        status=c.status,
        channel=c.channel,
        objective=c.objective,
        budget=c.budget,
        start_date=c.start_date,
        end_date=c.end_date,
        kpi_count=len(kpis),
        metric_count=len(metrics),
        latest_metrics=latest_metrics,
    )
