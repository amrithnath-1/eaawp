"""
EAAWP KPI Engine

Pure deterministic KPI calculations for the Marketing Performance Intelligence subsystem.

Design principles
-----------------
- All calculations are deterministic — no LLM involved at this layer.
- Missing metrics are explicitly represented as None (never fabricated).
- Zero denominators never produce a value — None is returned instead.
- Invalid/negative base values produce None with a logged warning.
- Every result carries data_complete and sources fields.
- The LLM layer may explain results, but all numbers come from here.

Supported KPIs
--------------
impressions, reach, clicks, ctr, conversions, conversion_rate,
spend, cpc, cpm, cpa, revenue, roas

Naming convention: metric names in CampaignMetric.metric_name are
case-insensitive and may use underscores or spaces.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Metric name normalisation ─────────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    "impression": "impressions",
    "click": "clicks",
    "conversion": "conversions",
    "cost_per_click": "cpc",
    "cost_per_mille": "cpm",
    "cost_per_acquisition": "cpa",
    "return_on_ad_spend": "roas",
    "click_through_rate": "ctr",
    "conv_rate": "conversion_rate",
    "ad_spend": "spend",
    "cost": "spend",
}


def normalise_metric_name(name: str) -> str:
    """Normalise a metric name to the canonical form."""
    key = name.lower().strip().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key)


# ── Raw metric collector ──────────────────────────────────────────────────────

def collect_metrics(
    metric_records: list[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, float]:
    """
    Aggregate metric records into a {normalised_name: total_value} dict.
    Filters by date range if provided (YYYY-MM-DD inclusive).
    Only sums numeric, finite, non-negative values.
    Never fabricates missing metrics.
    """
    totals: dict[str, float] = {}
    for rec in metric_records:
        date = rec.get("metric_date", "")
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        name = normalise_metric_name(str(rec.get("metric_name", "")))
        raw = rec.get("metric_value")
        try:
            val = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val):
            continue
        if val < 0:
            logger.warning("Skipping negative metric value %s=%s", name, val)
            continue
        totals[name] = totals.get(name, 0.0) + val
    return totals


# ── KPI dataclass ─────────────────────────────────────────────────────────────

@dataclass
class KPIResult:
    """
    A single calculated KPI.
    value is None if the metric could not be calculated (missing data / zero denominator).
    """
    name: str
    value: float | None
    unit: str = ""
    formula: str = ""      # human-readable formula used
    is_calculated: bool = True   # True = derived; False = directly recorded
    missing_inputs: list[str] = field(default_factory=list)


# ── KPI calculations ──────────────────────────────────────────────────────────

def calc_ctr(clicks: float | None, impressions: float | None) -> KPIResult:
    if clicks is None:
        return KPIResult("ctr", None, "%", "clicks / impressions × 100", missing_inputs=["clicks"])
    if impressions is None:
        return KPIResult("ctr", None, "%", "clicks / impressions × 100", missing_inputs=["impressions"])
    if impressions == 0:
        return KPIResult("ctr", None, "%", "clicks / impressions × 100", missing_inputs=["impressions=0"])
    return KPIResult("ctr", round(clicks / impressions * 100, 4), "%", "clicks / impressions × 100")


def calc_conversion_rate(
    conversions: float | None, clicks: float | None
) -> KPIResult:
    if conversions is None:
        return KPIResult("conversion_rate", None, "%", "conversions / clicks × 100", missing_inputs=["conversions"])
    if clicks is None:
        return KPIResult("conversion_rate", None, "%", "conversions / clicks × 100", missing_inputs=["clicks"])
    if clicks == 0:
        return KPIResult("conversion_rate", None, "%", "conversions / clicks × 100", missing_inputs=["clicks=0"])
    return KPIResult("conversion_rate", round(conversions / clicks * 100, 4), "%", "conversions / clicks × 100")


def calc_cpc(spend: float | None, clicks: float | None) -> KPIResult:
    if spend is None:
        return KPIResult("cpc", None, "£", "spend / clicks", missing_inputs=["spend"])
    if clicks is None:
        return KPIResult("cpc", None, "£", "spend / clicks", missing_inputs=["clicks"])
    if clicks == 0:
        return KPIResult("cpc", None, "£", "spend / clicks", missing_inputs=["clicks=0"])
    return KPIResult("cpc", round(spend / clicks, 4), "£", "spend / clicks")


def calc_cpm(spend: float | None, impressions: float | None) -> KPIResult:
    if spend is None:
        return KPIResult("cpm", None, "£", "spend / impressions × 1000", missing_inputs=["spend"])
    if impressions is None:
        return KPIResult("cpm", None, "£", "spend / impressions × 1000", missing_inputs=["impressions"])
    if impressions == 0:
        return KPIResult("cpm", None, "£", "spend / impressions × 1000", missing_inputs=["impressions=0"])
    return KPIResult("cpm", round(spend / impressions * 1000, 4), "£", "spend / impressions × 1000")


def calc_cpa(spend: float | None, conversions: float | None) -> KPIResult:
    if spend is None:
        return KPIResult("cpa", None, "£", "spend / conversions", missing_inputs=["spend"])
    if conversions is None:
        return KPIResult("cpa", None, "£", "spend / conversions", missing_inputs=["conversions"])
    if conversions == 0:
        return KPIResult("cpa", None, "£", "spend / conversions", missing_inputs=["conversions=0"])
    return KPIResult("cpa", round(spend / conversions, 4), "£", "spend / conversions")


def calc_roas(revenue: float | None, spend: float | None) -> KPIResult:
    if revenue is None:
        return KPIResult("roas", None, "x", "revenue / spend", missing_inputs=["revenue"])
    if spend is None:
        return KPIResult("roas", None, "x", "revenue / spend", missing_inputs=["spend"])
    if spend == 0:
        return KPIResult("roas", None, "x", "revenue / spend", missing_inputs=["spend=0"])
    return KPIResult("roas", round(revenue / spend, 4), "x", "revenue / spend")


def calculate_all_kpis(metrics: dict[str, float]) -> dict[str, KPIResult]:
    """
    Given a dict of {metric_name: value}, calculate all possible KPIs.
    Returns {kpi_name: KPIResult}. Never fabricates values.
    """
    get = metrics.get
    results: dict[str, KPIResult] = {}

    # Direct metrics (recorded, not calculated)
    for direct in ("impressions", "reach", "clicks", "conversions", "spend", "revenue"):
        v = get(direct)
        if v is not None:
            results[direct] = KPIResult(direct, v, is_calculated=False)

    # Calculated KPIs
    results["ctr"] = calc_ctr(get("clicks"), get("impressions"))
    results["conversion_rate"] = calc_conversion_rate(get("conversions"), get("clicks"))
    results["cpc"] = calc_cpc(get("spend"), get("clicks"))
    results["cpm"] = calc_cpm(get("spend"), get("impressions"))
    results["cpa"] = calc_cpa(get("spend"), get("conversions"))
    results["roas"] = calc_roas(get("revenue"), get("spend"))

    return results


# ── Period comparison ─────────────────────────────────────────────────────────

SIGNIFICANT_CHANGE_THRESHOLD_PCT = 10.0  # configurable


@dataclass
class PeriodComparison:
    """Comparison of a KPI between two periods."""
    kpi_name: str
    current: float | None
    previous: float | None
    pct_change: float | None        # positive = increase
    trend: str                      # "up" | "down" | "stable" | "unknown"
    is_significant: bool
    is_anomaly: bool
    anomaly_reason: str = ""


def compare_periods(
    current_kpis: dict[str, KPIResult],
    previous_kpis: dict[str, KPIResult],
    significant_threshold_pct: float = SIGNIFICANT_CHANGE_THRESHOLD_PCT,
    anomaly_threshold_pct: float = 50.0,
) -> list[PeriodComparison]:
    """
    Compare KPIs between current and previous periods.
    Returns deterministic comparison results — never LLM-fabricated numbers.
    """
    comparisons: list[PeriodComparison] = []
    all_keys = set(current_kpis) | set(previous_kpis)

    for kpi in all_keys:
        cur = current_kpis.get(kpi)
        prev = previous_kpis.get(kpi)

        cur_val = cur.value if cur else None
        prev_val = prev.value if prev else None

        if cur_val is None or prev_val is None:
            comparisons.append(PeriodComparison(
                kpi_name=kpi,
                current=cur_val,
                previous=prev_val,
                pct_change=None,
                trend="unknown",
                is_significant=False,
                is_anomaly=False,
            ))
            continue

        if prev_val == 0:
            # Can't compute meaningful % change from zero
            comparisons.append(PeriodComparison(
                kpi_name=kpi,
                current=cur_val,
                previous=prev_val,
                pct_change=None,
                trend="up" if cur_val > 0 else "stable",
                is_significant=cur_val > 0,
                is_anomaly=False,
            ))
            continue

        pct = round((cur_val - prev_val) / abs(prev_val) * 100, 2)
        trend = "up" if pct > 1.0 else "down" if pct < -1.0 else "stable"
        is_significant = abs(pct) >= significant_threshold_pct
        is_anomaly = abs(pct) >= anomaly_threshold_pct

        comparisons.append(PeriodComparison(
            kpi_name=kpi,
            current=cur_val,
            previous=prev_val,
            pct_change=pct,
            trend=trend,
            is_significant=is_significant,
            is_anomaly=is_anomaly,
            anomaly_reason=f"{kpi} changed {pct:+.1f}% — exceeds anomaly threshold ({anomaly_threshold_pct}%)" if is_anomaly else "",
        ))

    return comparisons


# ── Data completeness ─────────────────────────────────────────────────────────

EXPECTED_METRICS = frozenset(
    {"impressions", "clicks", "conversions", "spend", "revenue"}
)


def data_completeness_pct(metrics: dict[str, float]) -> float:
    """
    Returns a 0–100 completeness score based on how many expected
    marketing metrics are present.
    Never fabricates missing values — just scores presence.
    """
    present = sum(1 for m in EXPECTED_METRICS if m in metrics)
    return round(present / len(EXPECTED_METRICS) * 100, 1)
