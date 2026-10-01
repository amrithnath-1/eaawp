"""
EAAWP Funnel Schemas

Schema-agnostic funnel concept model.
Never assumes external table names or fixed CRM schemas.
All concepts are optional — missing stages are explicit, never fabricated.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

# Ordered funnel stages — not all need to be present
FUNNEL_STAGES = [
    "visitors",
    "leads",
    "qualified_leads",
    "opportunities",
    "customers",
]

# Semantic concept names the DMM may request from external data
FUNNEL_SEMANTIC_CONCEPTS = frozenset({
    "lead_count", "qualified_lead_count", "opportunity_count",
    "customer_count", "conversion_count", "revenue",
    "campaign_spend", "visitor_count",
})


@dataclass
class FunnelStage:
    """One stage of the funnel with its value and provenance."""
    name: str
    value: float | None          # None = data not available
    source: str = "unknown"      # "internal" | "external:concept_name" | "unknown"
    period: str = ""
    is_estimated: bool = False
    missing_reason: str = ""     # why value is None, if applicable


@dataclass
class FunnelConversionRate:
    """Conversion rate between two consecutive funnel stages."""
    from_stage: str
    to_stage: str
    rate_pct: float | None       # None if either stage missing or denominator zero
    from_value: float | None
    to_value: float | None
    missing_reason: str = ""


@dataclass
class FunnelMetrics:
    """
    Complete funnel analysis result.
    All numeric values are deterministic — never LLM-fabricated.
    """
    stages: list[FunnelStage]
    conversion_rates: list[FunnelConversionRate]
    overall_conversion_rate: FunnelConversionRate | None   # visitors→customers
    revenue: float | None
    spend: float | None
    cost_per_lead: float | None
    cost_per_customer: float | None           # CAC
    revenue_per_lead: float | None
    revenue_per_customer: float | None
    roas: float | None
    data_completeness_pct: float
    sources: list[str]
    findings: list[str]          # evidence-based text findings
    recommendations: list[str]   # evidence-based recommendations (text only)
    analysis_note: str = ""


@dataclass
class CampaignFunnelAttribution:
    """
    Funnel metrics attributed to a specific campaign.
    campaign_id links to EAAWP Campaign records.
    External concept names are from semantic mappings — not hardcoded tables.
    """
    campaign_id: str
    campaign_name: str
    funnel: FunnelMetrics
    external_concepts_used: list[str]   # which semantic concepts were queried
