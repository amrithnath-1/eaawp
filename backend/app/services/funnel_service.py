"""
EAAWP Lead & Customer Funnel Intelligence Service
"""
from __future__ import annotations

import logging
import math
from typing import Any

from app.schemas.funnel import (
    FUNNEL_STAGES,
    CampaignFunnelAttribution,
    FunnelConversionRate,
    FunnelMetrics,
    FunnelStage,
)
from app.schemas.data_access import CompanyDataQueryRequest
from app.services.data_access import execute_company_data_query

logger = logging.getLogger(__name__)

# ── Safe division ─────────────────────────────────────────────────────────────

def _safe_pct(numerator: float | None, denominator: float | None) -> tuple[float | None, str]:
    """Return (rate_pct, missing_reason). Never fabricates."""
    if numerator is None:
        return None, "numerator missing"
    if denominator is None:
        return None, "denominator missing"
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return None, "non-finite value"
    if denominator == 0:
        return None, "denominator is zero"
    return round(numerator / denominator * 100, 4), ""


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return None
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


# ── Funnel calculation ────────────────────────────────────────────────────────

def calculate_funnel(
    stage_values: dict[str, float | None],
    spend: float | None = None,
    revenue: float | None = None,
    period: str = "",
    sources: list[str] | None = None,
) -> FunnelMetrics:
    """
    Calculate funnel metrics from a dict of stage_name → value.
    Missing stages are represented as None — never fabricated.

    Args:
        stage_values: {stage_name: value | None} for any known stages.
        spend:        Optional spend value (for CAC, CPL, ROAS).
        revenue:      Optional revenue value.
        period:       Human-readable period label.
        sources:      Safe source labels.

    Returns:
        FunnelMetrics with all calculations and evidence.
    """
    # Build stage list in canonical order
    stages: list[FunnelStage] = []
    for name in FUNNEL_STAGES:
        raw = stage_values.get(name)
        val: float | None = None
        missing = ""
        if raw is not None:
            try:
                v = float(raw)
                if math.isfinite(v) and v >= 0:
                    val = v
                else:
                    missing = f"invalid value: {raw}"
            except (TypeError, ValueError):
                missing = f"non-numeric value: {raw}"
        else:
            missing = "not available"
        stages.append(FunnelStage(
            name=name, value=val,
            source=("internal" if val is not None else "unknown"),
            period=period,
            missing_reason=missing if val is None else "",
        ))

    stage_map = {s.name: s.value for s in stages}

    # Conversion rates between consecutive stages
    conversion_rates: list[FunnelConversionRate] = []
    for i in range(len(FUNNEL_STAGES) - 1):
        from_name = FUNNEL_STAGES[i]
        to_name = FUNNEL_STAGES[i + 1]
        fv = stage_map.get(from_name)
        tv = stage_map.get(to_name)
        rate, reason = _safe_pct(tv, fv)
        conversion_rates.append(FunnelConversionRate(
            from_stage=from_name, to_stage=to_name,
            rate_pct=rate, from_value=fv, to_value=tv,
            missing_reason=reason,
        ))

    # Overall visitors → customers
    visitors = stage_map.get("visitors")
    customers = stage_map.get("customers")
    overall_rate, overall_reason = _safe_pct(customers, visitors)
    overall = FunnelConversionRate(
        from_stage="visitors", to_stage="customers",
        rate_pct=overall_rate, from_value=visitors, to_value=customers,
        missing_reason=overall_reason,
    )

    # Leads for CPL / revenue_per_lead
    leads = stage_map.get("leads")

    # Derived efficiency metrics
    cpl = _safe_ratio(spend, leads)            # cost per lead
    cac = _safe_ratio(spend, customers)        # customer acquisition cost
    rpl = _safe_ratio(revenue, leads)          # revenue per lead
    rpc = _safe_ratio(revenue, customers)      # revenue per customer
    roas = _safe_ratio(revenue, spend)         # return on ad spend

    # Data completeness: how many of the 5 stages + revenue + spend are known
    present = sum(1 for v in [
        *[stage_map.get(s) for s in FUNNEL_STAGES], revenue, spend
    ] if v is not None)
    completeness = round(present / (len(FUNNEL_STAGES) + 2) * 100, 1)

    # Evidence-based findings
    findings, recommendations = _build_findings(
        stage_map, conversion_rates, spend, revenue, cac, completeness
    )

    note = ""
    if completeness < 30:
        note = f"Limited funnel data ({completeness:.0f}% complete). Treat analysis with caution."

    return FunnelMetrics(
        stages=stages,
        conversion_rates=conversion_rates,
        overall_conversion_rate=overall,
        revenue=revenue,
        spend=spend,
        cost_per_lead=cpl,
        cost_per_customer=cac,
        revenue_per_lead=rpl,
        revenue_per_customer=rpc,
        roas=roas,
        data_completeness_pct=completeness,
        sources=sources or [],
        findings=findings,
        recommendations=recommendations,
        analysis_note=note,
    )


# ── Finding builder ───────────────────────────────────────────────────────────

def _build_findings(
    stage_map: dict[str, float | None],
    conversion_rates: list[FunnelConversionRate],
    spend: float | None,
    revenue: float | None,
    cac: float | None,
    completeness: float,
) -> tuple[list[str], list[str]]:
    """Build evidence-based findings and recommendations. Never fabricates numbers."""
    findings: list[str] = []
    recommendations: list[str] = []
    comp_map = {f"{c.from_stage}_to_{c.to_stage}": c for c in conversion_rates}

    # Visitors → leads
    v2l = comp_map.get("visitors_to_leads")
    if v2l and v2l.rate_pct is not None:
        if v2l.rate_pct < 1.0:
            findings.append(
                f"Low visitor-to-lead conversion: {v2l.rate_pct:.2f}% "
                f"({v2l.to_value:.0f} leads from {v2l.from_value:.0f} visitors)."
            )
            recommendations.append(
                "Visitor-to-lead rate is below 1%. Review landing page experience and lead capture forms."
            )
        elif v2l.rate_pct >= 5.0:
            findings.append(
                f"Strong visitor-to-lead conversion: {v2l.rate_pct:.2f}%."
            )

    # Leads → customers
    l2c = comp_map.get("leads_to_customers")
    if not l2c:
        # Try qualified_leads → customers
        l2c = comp_map.get("qualified_leads_to_customers")
    if l2c and l2c.rate_pct is not None:
        if l2c.rate_pct < 5.0:
            findings.append(
                f"Weak lead-to-customer conversion: {l2c.rate_pct:.2f}% "
                f"({l2c.to_value:.0f} customers from {l2c.from_value:.0f} leads)."
            )
            recommendations.append(
                f"Only {l2c.rate_pct:.2f}% of leads convert to customers. "
                "Investigate nurturing sequences and sales qualification process."
            )

    # Spend vs revenue
    if spend is not None and revenue is not None:
        if revenue < spend:
            findings.append(
                f"Campaign spend (£{spend:,.0f}) exceeds revenue (£{revenue:,.0f}). "
                "Negative ROI detected."
            )
            recommendations.append(
                "Campaign is spending more than it generates. Review channel efficiency and targeting."
            )

    # CAC
    if cac is not None and revenue is not None:
        customers = stage_map.get("customers")
        if customers and customers > 0:
            rev_per_cust = revenue / customers
            if cac > rev_per_cust:
                findings.append(
                    f"CAC (£{cac:.2f}) exceeds revenue per customer (£{rev_per_cust:.2f}). "
                    "Acquisition is not profitable."
                )

    # Insufficient data
    if completeness < 30:
        findings.append(
            f"Only {completeness:.0f}% of funnel stages have data. "
            "Analysis is based on limited evidence."
        )

    return findings[:6], recommendations[:4]


# ── Serialise ─────────────────────────────────────────────────────────────────

def funnel_to_dict(funnel: FunnelMetrics) -> dict:
    """Safe serialisation — no credentials, no raw SQL."""
    return {
        "stages": [
            {
                "name": s.name, "value": s.value, "source": s.source,
                "period": s.period, "missing_reason": s.missing_reason,
            }
            for s in funnel.stages
        ],
        "conversion_rates": [
            {
                "from_stage": c.from_stage, "to_stage": c.to_stage,
                "rate_pct": c.rate_pct, "from_value": c.from_value,
                "to_value": c.to_value, "missing_reason": c.missing_reason,
            }
            for c in funnel.conversion_rates
        ],
        "overall_conversion_rate": {
            "rate_pct": funnel.overall_conversion_rate.rate_pct,
            "from_value": funnel.overall_conversion_rate.from_value,
            "to_value": funnel.overall_conversion_rate.to_value,
            "missing_reason": funnel.overall_conversion_rate.missing_reason,
        } if funnel.overall_conversion_rate else None,
        "revenue": funnel.revenue,
        "spend": funnel.spend,
        "cost_per_lead": funnel.cost_per_lead,
        "cost_per_customer": funnel.cost_per_customer,
        "revenue_per_lead": funnel.revenue_per_lead,
        "revenue_per_customer": funnel.revenue_per_customer,
        "roas": funnel.roas,
        "data_completeness_pct": funnel.data_completeness_pct,
        "sources": funnel.sources,
        "findings": funnel.findings,
        "recommendations": funnel.recommendations,
        "analysis_note": funnel.analysis_note,
    }


# ── Fetch from external data via semantic mapping ─────────────────────────────

async def fetch_funnel_from_external(
    tenant_id: str,
    role_key: str,
    concepts: list[str],
    db,
) -> dict[str, float | None]:
    """
    Retrieve funnel stage values from authorized external company data
    via the existing controlled semantic mapping / query_company_data layer.
    """
    results: dict[str, float | None] = {}

    for concept in concepts:
        try:
            request = CompanyDataQueryRequest(
                semantic_concept=concept,
                fields=[],
                filters=[],
                sort=[],
                limit=200,
            )
            response = await execute_company_data_query(
                request=request,
                tenant_id=tenant_id,
                role_key=role_key,
                db=db,
            )
            total = 0.0
            found_any = False
            for row in response.rows:
                for v in row.values():
                    try:
                        fv = float(v)  # type: ignore[arg-type]
                        if math.isfinite(fv) and fv >= 0:
                            total += fv
                            found_any = True
                    except (TypeError, ValueError):
                        pass
            results[concept] = total if found_any else None
        except PermissionError:
            logger.info("Concept '%s' not accessible for tenant %s", concept, tenant_id)
            results[concept] = None
        except ValueError:
            logger.info("No mapping for concept '%s' in tenant %s", concept, tenant_id)
            results[concept] = None
        except Exception as exc:
            logger.warning("Error fetching concept '%s': %s", concept, exc)
            results[concept] = None

    return results
