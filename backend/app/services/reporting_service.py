"""
EAAWP Reporting Service

Generates deterministic marketing summaries from existing subsystems.
Never fabricates metrics. Uses actual stored data only.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.campaign_models import Campaign, CampaignMetric
from app.db.content_models import ContentItem
from app.db.strategy_models import MarketingObjective
from app.db.monitoring_models import MonitoringAuditLog

logger = logging.getLogger(__name__)


async def generate_marketing_summary(
    tenant_id: str, db: AsyncSession, period_days: int = 7,
) -> dict:
    """
    Generate a safe marketing summary for the given period.
    Uses only stored data — no fabrication.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=period_days)
    since_str = since.strftime("%Y-%m-%d")

    # Campaigns
    cam_result = await db.execute(
        select(Campaign).where(Campaign.tenant_id == tenant_id)
    )
    all_campaigns = cam_result.scalars().all()
    active_campaigns = [c for c in all_campaigns if c.status == "active"]
    campaign_summary = {
        "total": len(all_campaigns),
        "active": len(active_campaigns),
        "by_status": {},
    }
    for c in all_campaigns:
        campaign_summary["by_status"][c.status] = campaign_summary["by_status"].get(c.status, 0) + 1

    # Metrics recorded in period
    metric_result = await db.execute(
        select(CampaignMetric).where(
            CampaignMetric.tenant_id == tenant_id,
            CampaignMetric.metric_date >= since_str,
        )
    )
    metrics = metric_result.scalars().all()
    metric_names = list({m.metric_name for m in metrics})

    # Objectives
    obj_result = await db.execute(
        select(MarketingObjective).where(MarketingObjective.tenant_id == tenant_id)
    )
    objectives = obj_result.scalars().all()
    objective_summary = {
        "total": len(objectives),
        "active": len([o for o in objectives if o.status == "active"]),
        "achieved": len([o for o in objectives if o.status == "achieved"]),
    }

    # Content
    content_result = await db.execute(
        select(ContentItem).where(ContentItem.tenant_id == tenant_id)
    )
    content_items = content_result.scalars().all()
    content_summary = {
        "total": len(content_items),
        "by_type": {},
        "by_status": {},
    }
    for ci in content_items:
        content_summary["by_type"][ci.content_type] = content_summary["by_type"].get(ci.content_type, 0) + 1
        content_summary["by_status"][ci.status] = content_summary["by_status"].get(ci.status, 0) + 1

    # Monitoring events in period
    mon_result = await db.execute(
        select(MonitoringAuditLog).where(
            MonitoringAuditLog.tenant_id == tenant_id,
            MonitoringAuditLog.evaluated_at >= since,
        )
    )
    mon_logs = mon_result.scalars().all()
    triggered = [m for m in mon_logs if m.triggered]

    return {
        "report_type": "marketing_summary",
        "tenant_id": tenant_id,
        "period_days": period_days,
        "generated_at": now.isoformat(),
        "campaigns": campaign_summary,
        "metrics_recorded": len(metrics),
        "metric_names": metric_names[:10],
        "objectives": objective_summary,
        "content": content_summary,
        "monitoring": {
            "evaluations": len(mon_logs),
            "triggered": len(triggered),
        },
        "note": "All values are from recorded data. No metrics are fabricated.",
    }
