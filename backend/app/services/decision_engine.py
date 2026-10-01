"""
EAAWP Decision Engine

Deterministic prioritization of marketing issues and opportunities.

Scoring formula (explicit and documented)
-----------------------------------------
priority_score = (
    business_impact_score   * 0.35   # how significant is the impact
  + urgency_score           * 0.25   # how time-sensitive
  + magnitude_score         * 0.20   # size of the change/gap
  + confidence_score        * 0.20   # data quality / completeness
) * 100

Component definitions
---------------------
business_impact_score (0–1):
    critical  = 1.0   (revenue/customer loss, negative ROI)
    high      = 0.75  (significant KPI decline, funnel drop)
    medium    = 0.50  (moderate underperformance)
    low       = 0.25  (minor efficiency gap)

urgency_score (0–1):
    Based on magnitude of change from previous period:
    |pct_change| >= 50% → 1.0
    |pct_change| >= 25% → 0.75
    |pct_change| >= 10% → 0.50
    otherwise           → 0.25

magnitude_score (0–1):
    Based on absolute metric value vs expected:
    Normalised to 0–1 using tanh(value / scale).

confidence_score (0–1):
    Directly = data_completeness_pct / 100

LLM role
--------
The LLM may *explain* or *present* priorities, but all scores
come from this engine. The LLM must not override numeric scores.
"""
from __future__ import annotations

import math
from typing import Any

from app.schemas.strategy import MarketingPriority


# ── Scoring components ────────────────────────────────────────────────────────

def _business_impact_score(severity: str) -> float:
    return {"critical": 1.0, "high": 0.75, "medium": 0.50, "low": 0.25}.get(severity, 0.25)


def _urgency_score(pct_change: float | None) -> float:
    if pct_change is None:
        return 0.25
    abs_change = abs(pct_change)
    if abs_change >= 50:
        return 1.0
    if abs_change >= 25:
        return 0.75
    if abs_change >= 10:
        return 0.50
    return 0.25


def _magnitude_score(value: float | None, scale: float = 100.0) -> float:
    """Normalise via tanh — asymptotes to 1 as value grows."""
    if value is None or value <= 0:
        return 0.0
    return math.tanh(value / scale)


def _confidence_score(completeness_pct: float) -> float:
    return max(0.0, min(1.0, completeness_pct / 100.0))


# ── Main scoring function ─────────────────────────────────────────────────────

def compute_priority_score(
    severity: str,
    pct_change: float | None,
    magnitude_value: float | None,
    data_completeness: float,
    magnitude_scale: float = 100.0,
) -> float:
    """
    Compute a deterministic priority score in range 0–100.

    Weights: business_impact=0.35, urgency=0.25, magnitude=0.20, confidence=0.20
    """
    bi = _business_impact_score(severity)
    urg = _urgency_score(pct_change)
    mag = _magnitude_score(magnitude_value, magnitude_scale)
    conf = _confidence_score(data_completeness)

    raw = bi * 0.35 + urg * 0.25 + mag * 0.20 + conf * 0.20
    return round(raw * 100, 2)


# ── Priority builder helpers ──────────────────────────────────────────────────

def _severity_from_pct(pct_change: float | None) -> str:
    if pct_change is None:
        return "low"
    abs_c = abs(pct_change)
    if abs_c >= 50:
        return "critical"
    if abs_c >= 25:
        return "high"
    if abs_c >= 10:
        return "medium"
    return "low"


def build_priorities_from_kpi_comparisons(
    comparisons: list[dict[str, Any]],
    campaign_name: str,
    campaign_id: str,
    data_completeness: float,
    sources: list[str],
) -> list[MarketingPriority]:
    """
    Build MarketingPriority objects from KPI period comparisons.
    Only creates priorities where there is actual evidence.
    """
    priorities: list[MarketingPriority] = []

    for comp in comparisons:
        pct = comp.get("pct_change")
        kpi = comp.get("kpi_name", "")
        current = comp.get("current")
        previous = comp.get("previous")
        is_anomaly = comp.get("is_anomaly", False)
        is_significant = comp.get("is_significant", False)

        if not is_significant and not is_anomaly:
            continue
        if pct is None or current is None:
            continue

        severity = _severity_from_pct(pct)
        direction = "decreased" if pct < 0 else "increased"
        score = compute_priority_score(
            severity=severity,
            pct_change=pct,
            magnitude_value=abs(current - (previous or 0)),
            data_completeness=data_completeness,
        )

        evidence = [
            f"{kpi} {direction} {abs(pct):.1f}% "
            f"(current: {current:.4g}, previous: {previous:.4g})"
        ]
        if is_anomaly:
            evidence.append(f"Anomaly detected: change exceeds anomaly threshold.")

        category = "problem" if pct < 0 else "opportunity"
        recommended = (
            f"Investigate {kpi} decline in campaign '{campaign_name}'. "
            "Consider reviewing targeting, creative, or budget allocation."
        ) if pct < 0 else (
            f"{kpi} improved in '{campaign_name}'. Consider scaling this approach."
        )

        priorities.append(MarketingPriority(
            title=f"{kpi.upper()} {direction} {abs(pct):.0f}% — {campaign_name}",
            category=category,
            severity=severity,
            description=f"{kpi} has {direction} {abs(pct):.1f}% compared with the previous period.",
            evidence=evidence,
            affected_campaigns=[campaign_id],
            affected_funnel_stage="",
            kpi_impact=f"{kpi}: {current:.4g}",
            confidence=_confidence_score(data_completeness),
            data_completeness=data_completeness,
            recommended_next_step=recommended,
            required_approval="high" if severity in ("critical", "high") else "medium",
            priority_score=score,
            sources=sources,
        ))

    return sorted(priorities, key=lambda p: p.priority_score, reverse=True)


def build_priorities_from_funnel(
    funnel: dict[str, Any],
    campaign_name: str,
    campaign_id: str,
) -> list[MarketingPriority]:
    """Build priorities from funnel analysis findings."""
    priorities: list[MarketingPriority] = []
    completeness = funnel.get("data_completeness_pct", 0.0)
    sources = funnel.get("sources", [])

    for finding in funnel.get("findings", []):
        # Determine severity from finding text
        severity = "medium"
        if any(w in finding.lower() for w in ("negative", "exceed", "weak")):
            severity = "high"
        if "negative roi" in finding.lower():
            severity = "critical"

        score = compute_priority_score(
            severity=severity,
            pct_change=None,
            magnitude_value=None,
            data_completeness=completeness,
        )
        priorities.append(MarketingPriority(
            title=f"Funnel issue — {campaign_name}",
            category="problem",
            severity=severity,
            description=finding,
            evidence=[finding],
            affected_campaigns=[campaign_id],
            affected_funnel_stage="funnel",
            kpi_impact="",
            confidence=_confidence_score(completeness),
            data_completeness=completeness,
            recommended_next_step=funnel.get("recommendations", ["Review funnel performance."])[0]
                if funnel.get("recommendations") else "Review funnel data.",
            required_approval="medium",
            priority_score=score,
            sources=sources,
        ))

    return sorted(priorities, key=lambda p: p.priority_score, reverse=True)


# ── Sort and deduplicate ──────────────────────────────────────────────────────

def rank_priorities(priorities: list[MarketingPriority]) -> list[MarketingPriority]:
    """Return priorities sorted by score descending, deduped by title."""
    seen: set[str] = set()
    unique: list[MarketingPriority] = []
    for p in sorted(priorities, key=lambda x: x.priority_score, reverse=True):
        if p.title not in seen:
            seen.add(p.title)
            unique.append(p)
    return unique
