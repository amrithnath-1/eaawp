"""
EAAWP Performance Analysis Service

Analyses campaign performance over a period, compares to prior period,
detects trends/anomalies, and produces structured PerformanceInsight results.

Data sources
------------
A. EAAWP CampaignMetric records (internal, always available for tracked campaigns)
B. External company data via query_company_data / semantic mappings (optional)

Security / integrity invariants
---------------------------------
- All numeric values originate from deterministic KPI calculations — never fabricated.
- Tenant isolation enforced on every DB query.
- No credentials, connection strings, or raw SQL in any output.
- Missing data is explicit (None / completeness score) — never silently filled.
- External data is accessed only via the existing semantic mapping layer.
- Recommendations are based on available evidence only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.campaign_models import Campaign, CampaignMetric
from app.services.kpi_engine import (
    KPIResult,
    PeriodComparison,
    calculate_all_kpis,
    collect_metrics,
    compare_periods,
    data_completeness_pct,
)

logger = logging.getLogger(__name__)


# ── Output structures ─────────────────────────────────────────────────────────

@dataclass
class PerformanceInsight:
    """
    Structured performance analysis result.
    All numeric claims are deterministic — never LLM-fabricated.
    """
    campaign_id: str
    campaign_name: str
    period_from: str | None
    period_to: str | None
    kpis: dict[str, KPIResult]
    comparisons: list[PeriodComparison]
    strongest_metrics: list[str]       # KPI names with best performance
    weakest_metrics: list[str]         # KPI names with worst performance
    anomalies: list[str]               # human-readable anomaly descriptions
    data_completeness_pct: float
    sources: list[str]                 # safe source labels
    recommendations: list[str]         # evidence-based text recommendations
    analysis_note: str = ""            # e.g. "Limited data — treat with caution"


@dataclass
class CampaignComparison:
    """Comparison of multiple campaigns on selected KPIs."""
    campaigns: list[dict[str, Any]]    # [{id, name, kpi_values}]
    kpis_compared: list[str]
    ranked_by: str | None
    ranking: list[str]                 # campaign IDs in rank order
    insufficient_data: bool
    insufficient_reason: str = ""
    sources: list[str] = field(default_factory=list)


# ── Period helpers ────────────────────────────────────────────────────────────

def _prior_period(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """
    Given a current period, return the same-length prior period.
    Returns (None, None) if period cannot be inferred.
    """
    if not date_from or not date_to:
        return None, None
    try:
        from datetime import date, timedelta
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
        length = (d_to - d_from).days + 1
        prior_to = d_from - timedelta(days=1)
        prior_from = prior_to - timedelta(days=length - 1)
        return str(prior_from), str(prior_to)
    except Exception:
        return None, None


# ── Recommendation builder ────────────────────────────────────────────────────

def _build_recommendations(
    kpis: dict[str, KPIResult],
    comparisons: list[PeriodComparison],
    anomalies: list[str],
    completeness: float,
) -> list[str]:
    """
    Generate evidence-based, actionable recommendations.
    Every recommendation references a deterministic KPI value or comparison.
    Never invents data or suggests actions without supporting evidence.
    """
    recs: list[str] = []
    comp_map = {c.kpi_name: c for c in comparisons}

    # Low CTR
    ctr_kpi = kpis.get("ctr")
    if ctr_kpi and ctr_kpi.value is not None and ctr_kpi.value < 1.0:
        recs.append(
            f"CTR is {ctr_kpi.value:.2f}% — below typical benchmarks. "
            "Consider reviewing ad creative and audience targeting."
        )

    # CTR declined significantly
    ctr_comp = comp_map.get("ctr")
    if ctr_comp and ctr_comp.pct_change is not None and ctr_comp.pct_change < -10:
        recs.append(
            f"CTR decreased {ctr_comp.pct_change:.1f}% vs previous period "
            f"({ctr_comp.previous:.2f}% → {ctr_comp.current:.2f}%). "
            "Investigate targeting or creative fatigue."
        )

    # High CPA
    cpa_kpi = kpis.get("cpa")
    if cpa_kpi and cpa_kpi.value is not None and cpa_kpi.value > 0:
        cpa_comp = comp_map.get("cpa")
        if cpa_comp and cpa_comp.pct_change is not None and cpa_comp.pct_change > 20:
            recs.append(
                f"CPA increased {cpa_comp.pct_change:.1f}% to £{cpa_kpi.value:.2f}. "
                "Review bid strategy and conversion funnel."
            )

    # Low ROAS
    roas_kpi = kpis.get("roas")
    if roas_kpi and roas_kpi.value is not None and roas_kpi.value < 1.0:
        recs.append(
            f"ROAS is {roas_kpi.value:.2f}x — campaign is spending more than it returns. "
            "Review budget allocation and channel efficiency."
        )

    # Anomalies
    for anomaly in anomalies[:3]:
        recs.append(f"Anomaly detected: {anomaly}. Investigate before next campaign cycle.")

    # Low data completeness
    if completeness < 50:
        recs.append(
            f"Data completeness is {completeness:.0f}%. "
            "Record additional metrics (impressions, spend, revenue) for more reliable analysis."
        )

    return recs[:6]  # cap to avoid overwhelming output


# ── Main analysis function ────────────────────────────────────────────────────

async def analyse_campaign_performance(
    campaign_id: str,
    tenant_id: str,
    db: AsyncSession,
    date_from: str | None = None,
    date_to: str | None = None,
    external_metrics: dict[str, float] | None = None,
    external_sources: list[str] | None = None,
) -> PerformanceInsight | None:
    """
    Analyse campaign performance over a period.

    Args:
        campaign_id:       EAAWP campaign ID.
        tenant_id:         Tenant (enforces isolation).
        db:                Async database session.
        date_from/date_to: Analysis period (YYYY-MM-DD). None = all recorded data.
        external_metrics:  Optional additional metrics from query_company_data.
        external_sources:  Safe source labels for external data.

    Returns:
        PerformanceInsight or None if campaign not found / wrong tenant.
    """
    # Verify campaign belongs to tenant
    cam_result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    campaign = cam_result.scalar_one_or_none()
    if not campaign:
        return None

    # Load internal metrics
    stmt = select(CampaignMetric).where(
        CampaignMetric.campaign_id == campaign_id,
        CampaignMetric.tenant_id == tenant_id,
    )
    if date_from:
        stmt = stmt.where(CampaignMetric.metric_date >= date_from)
    if date_to:
        stmt = stmt.where(CampaignMetric.metric_date <= date_to)
    metric_result = await db.execute(stmt)
    metric_rows = metric_result.scalars().all()

    # Convert to dicts for kpi_engine
    internal_records = [
        {
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "metric_date": m.metric_date,
        }
        for m in metric_rows
    ]

    # Aggregate metrics
    aggregated = collect_metrics(internal_records, date_from, date_to)

    # Merge external metrics if provided
    sources = [f"EAAWP campaign metrics ({len(metric_rows)} records)"]
    if external_metrics:
        for k, v in external_metrics.items():
            if k not in aggregated:  # don't overwrite internal
                aggregated[k] = v
        sources.extend(external_sources or ["External company data"])

    # Calculate KPIs
    kpis = calculate_all_kpis(aggregated)

    # Prior period comparison
    prior_from, prior_to = _prior_period(date_from, date_to)
    comparisons: list[PeriodComparison] = []
    if prior_from and prior_to:
        prior_stmt = select(CampaignMetric).where(
            CampaignMetric.campaign_id == campaign_id,
            CampaignMetric.tenant_id == tenant_id,
            CampaignMetric.metric_date >= prior_from,
            CampaignMetric.metric_date <= prior_to,
        )
        prior_result = await db.execute(prior_stmt)
        prior_records = [
            {"metric_name": m.metric_name, "metric_value": m.metric_value, "metric_date": m.metric_date}
            for m in prior_result.scalars().all()
        ]
        prior_agg = collect_metrics(prior_records, prior_from, prior_to)
        prior_kpis = calculate_all_kpis(prior_agg)
        comparisons = compare_periods(kpis, prior_kpis)

    # Identify strongest / weakest metrics (only where we have values)
    scored = {
        k: v.value for k, v in kpis.items()
        if v.value is not None and not v.is_calculated
    }
    ranked = sorted(scored, key=lambda k: scored[k], reverse=True)
    strongest = ranked[:3]
    weakest = ranked[-3:] if len(ranked) > 3 else []

    # Anomalies
    anomalies = [c.anomaly_reason for c in comparisons if c.is_anomaly and c.anomaly_reason]

    # Completeness
    completeness = data_completeness_pct(aggregated)

    # Analysis note
    note = ""
    if len(metric_rows) == 0 and not external_metrics:
        note = "No metric data recorded for this period."
    elif completeness < 40:
        note = f"Limited data ({completeness:.0f}% complete) — treat analysis with caution."

    # Recommendations
    recommendations = _build_recommendations(kpis, comparisons, anomalies, completeness)

    return PerformanceInsight(
        campaign_id=campaign_id,
        campaign_name=campaign.name,
        period_from=date_from,
        period_to=date_to,
        kpis=kpis,
        comparisons=comparisons,
        strongest_metrics=strongest,
        weakest_metrics=weakest,
        anomalies=anomalies,
        data_completeness_pct=completeness,
        sources=sources,
        recommendations=recommendations,
        analysis_note=note,
    )


# ── Campaign comparison ───────────────────────────────────────────────────────

async def compare_campaigns(
    campaign_ids: list[str],
    tenant_id: str,
    db: AsyncSession,
    date_from: str | None = None,
    date_to: str | None = None,
    rank_by: str = "ctr",
) -> CampaignComparison:
    """
    Compare multiple campaigns on key KPIs.
    Returns ranked results only when sufficient data exists.
    Never fabricates values for missing metrics.
    """
    if len(campaign_ids) < 2:
        return CampaignComparison(
            campaigns=[],
            kpis_compared=[],
            ranked_by=None,
            ranking=[],
            insufficient_data=True,
            insufficient_reason="At least 2 campaigns required for comparison.",
        )

    campaign_data: list[dict[str, Any]] = []
    sources: list[str] = []

    for cid in campaign_ids:
        insight = await analyse_campaign_performance(
            campaign_id=cid,
            tenant_id=tenant_id,
            db=db,
            date_from=date_from,
            date_to=date_to,
        )
        if insight is None:
            continue

        kpi_values = {
            k: v.value for k, v in insight.kpis.items()
        }
        campaign_data.append({
            "id": cid,
            "name": insight.campaign_name,
            "kpi_values": kpi_values,
            "completeness": insight.data_completeness_pct,
        })
        sources.extend(insight.sources)

    if len(campaign_data) < 2:
        return CampaignComparison(
            campaigns=campaign_data,
            kpis_compared=[],
            ranked_by=None,
            ranking=[],
            insufficient_data=True,
            insufficient_reason="Insufficient campaign data for comparison.",
        )

    # Rank by the requested KPI — only if all campaigns have that value
    rank_values = {
        c["id"]: c["kpi_values"].get(rank_by)
        for c in campaign_data
    }
    has_all_rank_values = all(v is not None for v in rank_values.values())

    if has_all_rank_values:
        ranked_ids = sorted(
            rank_values, key=lambda cid: rank_values[cid] or 0, reverse=True
        )
    else:
        ranked_ids = [c["id"] for c in campaign_data]

    all_kpi_names = sorted(
        {k for c in campaign_data for k in c["kpi_values"]}
    )

    return CampaignComparison(
        campaigns=campaign_data,
        kpis_compared=all_kpi_names,
        ranked_by=rank_by if has_all_rank_values else None,
        ranking=ranked_ids,
        insufficient_data=not has_all_rank_values,
        insufficient_reason="" if has_all_rank_values else (
            f"Cannot rank: '{rank_by}' missing for some campaigns."
        ),
        sources=list(dict.fromkeys(sources)),
    )


# ── Safe serialisation ────────────────────────────────────────────────────────

def insight_to_dict(insight: PerformanceInsight) -> dict[str, Any]:
    """
    Serialise a PerformanceInsight to a safe dict for API responses.
    Never includes credentials or internal infrastructure details.
    """
    return {
        "campaign_id": insight.campaign_id,
        "campaign_name": insight.campaign_name,
        "period_from": insight.period_from,
        "period_to": insight.period_to,
        "kpis": {
            k: {
                "value": v.value,
                "unit": v.unit,
                "formula": v.formula,
                "is_calculated": v.is_calculated,
                "missing_inputs": v.missing_inputs,
            }
            for k, v in insight.kpis.items()
        },
        "comparisons": [
            {
                "kpi_name": c.kpi_name,
                "current": c.current,
                "previous": c.previous,
                "pct_change": c.pct_change,
                "trend": c.trend,
                "is_significant": c.is_significant,
                "is_anomaly": c.is_anomaly,
                "anomaly_reason": c.anomaly_reason,
            }
            for c in insight.comparisons
        ],
        "strongest_metrics": insight.strongest_metrics,
        "weakest_metrics": insight.weakest_metrics,
        "anomalies": insight.anomalies,
        "data_completeness_pct": insight.data_completeness_pct,
        "sources": insight.sources,
        "recommendations": insight.recommendations,
        "analysis_note": insight.analysis_note,
    }
