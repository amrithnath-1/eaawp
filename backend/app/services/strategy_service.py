"""
EAAWP Marketing Strategy Service

Combines campaign performance + funnel intelligence + monitoring findings
+ company knowledge into a structured StrategicAnalysis.

Security invariants
-------------------
- Never fabricates data — all evidence comes from existing services.
- Never exposes credentials, SQL, or connection details.
- Tenant isolation on all DB queries.
- Recommendations are text only — they never execute actions.
- RAG sources are included but never override tool permissions or security.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.strategy_models import MarketingObjective
from app.schemas.strategy import (
    CreateObjectiveInput, ObjectiveOut, ObjectiveUpdate, StrategicAnalysis,
    VALID_OBJECTIVE_TYPES, VALID_STATUSES,
)
from app.services.decision_engine import (
    build_priorities_from_funnel,
    build_priorities_from_kpi_comparisons,
    rank_priorities,
)

logger = logging.getLogger(__name__)


# ── Objective CRUD ─────────────────────────────────────────────────────────────

def _obj_to_out(o: MarketingObjective) -> ObjectiveOut:
    return ObjectiveOut(
        id=o.id, tenant_id=o.tenant_id, name=o.name, description=o.description,
        objective_type=o.objective_type, priority=o.priority, status=o.status,
        target_metric=o.target_metric, target_value=o.target_value,
        current_value=o.current_value, start_date=o.start_date, target_date=o.target_date,
        linked_campaign_ids=json.loads(o.linked_campaign_ids_json or "[]"),
        created_by=o.created_by, created_at=o.created_at, updated_at=o.updated_at,
    )


async def create_objective(body: CreateObjectiveInput, tenant_id: str, db: AsyncSession) -> ObjectiveOut:
    obj = MarketingObjective(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name=body.name, description=body.description,
        objective_type=body.objective_type, priority=body.priority,
        status="draft", target_metric=body.target_metric,
        target_value=body.target_value, created_by=body.created_by,
        linked_campaign_ids_json="[]",
    )
    db.add(obj)
    await db.flush()
    return _obj_to_out(obj)


async def list_objectives(tenant_id: str, db: AsyncSession, status: str | None = None) -> list[ObjectiveOut]:
    stmt = select(MarketingObjective).where(MarketingObjective.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(MarketingObjective.status == status)
    stmt = stmt.order_by(MarketingObjective.priority, MarketingObjective.created_at.desc())
    result = await db.execute(stmt)
    return [_obj_to_out(o) for o in result.scalars().all()]


async def get_objective(obj_id: str, tenant_id: str, db: AsyncSession) -> ObjectiveOut | None:
    result = await db.execute(
        select(MarketingObjective).where(
            MarketingObjective.id == obj_id, MarketingObjective.tenant_id == tenant_id)
    )
    o = result.scalar_one_or_none()
    return _obj_to_out(o) if o else None


async def update_objective(obj_id: str, body: ObjectiveUpdate, tenant_id: str, db: AsyncSession) -> ObjectiveOut | None:
    result = await db.execute(
        select(MarketingObjective).where(
            MarketingObjective.id == obj_id, MarketingObjective.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        return None
    if body.name is not None:
        obj.name = body.name
    if body.description is not None:
        obj.description = body.description
    if body.objective_type is not None:
        obj.objective_type = body.objective_type
    if body.priority is not None:
        obj.priority = body.priority
    if body.status is not None:
        obj.status = body.status
    if body.target_metric is not None:
        obj.target_metric = body.target_metric
    if body.target_value is not None:
        obj.target_value = body.target_value
    if body.current_value is not None:
        obj.current_value = body.current_value
    if body.start_date is not None:
        obj.start_date = body.start_date
    if body.target_date is not None:
        obj.target_date = body.target_date
    if body.linked_campaign_ids is not None:
        obj.linked_campaign_ids_json = json.dumps(body.linked_campaign_ids)
    await db.flush()
    return _obj_to_out(obj)


# ── Strategic analysis ─────────────────────────────────────────────────────────

async def build_strategic_analysis(
    tenant_id: str,
    db: AsyncSession,
    campaign_insights: list[dict[str, Any]] | None = None,
    funnel_insights: list[dict[str, Any]] | None = None,
    monitoring_anomalies: list[str] | None = None,
    rag_context: str = "",
    rag_sources: list[str] | None = None,
) -> StrategicAnalysis:
    """
    Combine available intelligence into a structured strategic analysis.
    Never fabricates data — all evidence must come from provided insights.
    """
    from app.services.decision_engine import MarketingPriority

    all_priorities: list[MarketingPriority] = []
    uncertainties: list[str] = []
    sources: list[str] = []
    total_completeness: list[float] = []

    # Build from campaign insights (KPI comparisons)
    for ci in (campaign_insights or []):
        comps = ci.get("comparisons", [])
        campaign_name = ci.get("campaign_name", "unknown")
        campaign_id = ci.get("campaign_id", "")
        completeness = ci.get("data_completeness_pct", 0.0)
        total_completeness.append(completeness)
        if ci.get("sources"):
            sources.extend(ci["sources"])
        if comps:
            priorities = build_priorities_from_kpi_comparisons(
                comparisons=comps, campaign_name=campaign_name,
                campaign_id=campaign_id, data_completeness=completeness,
                sources=ci.get("sources", []),
            )
            all_priorities.extend(priorities)
        if completeness < 40:
            uncertainties.append(f"Campaign '{campaign_name}' has limited data ({completeness:.0f}% complete).")

    # Build from funnel insights
    for fi in (funnel_insights or []):
        campaign_name = fi.get("campaign_name", "funnel")
        campaign_id = fi.get("campaign_id", "")
        completeness = fi.get("data_completeness_pct", 0.0)
        total_completeness.append(completeness)
        if fi.get("sources"):
            sources.extend(fi["sources"])
        priorities = build_priorities_from_funnel(fi, campaign_name, campaign_id)
        all_priorities.extend(priorities)

    # Add monitoring anomalies as critical priorities
    for anomaly in (monitoring_anomalies or []):
        from app.services.decision_engine import compute_priority_score
        score = compute_priority_score("high", None, None, 80.0)
        all_priorities.append(MarketingPriority(
            title=f"Monitoring alert: {anomaly[:60]}",
            category="monitoring_alert",
            severity="high",
            description=anomaly,
            evidence=[f"Monitoring system detected: {anomaly}"],
            affected_campaigns=[],
            affected_funnel_stage="",
            kpi_impact="",
            confidence=0.8,
            data_completeness=80.0,
            recommended_next_step="Investigate the triggered condition. Use analyze_campaign_performance for details.",
            required_approval="medium",
            priority_score=score,
            sources=["Monitoring engine"],
        ))

    ranked = rank_priorities(all_priorities)
    problems = [p for p in ranked if p.category in ("problem", "risk", "monitoring_alert")]
    opportunities = [p for p in ranked if p.category == "opportunity"]

    # Active objectives
    objective_rows = await list_objectives(tenant_id, db, status="active")
    active_objectives = [
        {"id": o.id, "name": o.name, "type": o.objective_type, "priority": o.priority,
         "target_metric": o.target_metric, "target_value": o.target_value,
         "current_value": o.current_value, "status": o.status}
        for o in objective_rows
    ]

    # Recommended actions (text only — never execute)
    recommended_actions: list[str] = []
    for p in ranked[:5]:
        recommended_actions.append(
            f"[{p.severity.upper()}] {p.recommended_next_step} "
            f"(score: {p.priority_score:.0f}, approval: {p.required_approval})"
        )
    if not recommended_actions:
        recommended_actions.append("No significant issues detected with available data.")

    # Current situation summary
    n_problems = len(problems)
    n_opportunities = len(opportunities)
    avg_completeness = (sum(total_completeness) / len(total_completeness)) if total_completeness else 0.0
    situation = (
        f"{n_problems} problem(s) and {n_opportunities} opportunity(ies) identified "
        f"from {len(campaign_insights or [])} campaign(s). "
        f"Average data completeness: {avg_completeness:.0f}%."
    )

    if not total_completeness:
        uncertainties.append("No campaign performance or funnel data was provided.")
    if rag_context:
        sources.append("Company knowledge base")
    if rag_sources:
        sources.extend(rag_sources)

    return StrategicAnalysis(
        tenant_id=tenant_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_situation=situation,
        top_problems=problems[:5],
        top_opportunities=opportunities[:5],
        all_priorities=ranked,
        active_objectives=active_objectives,
        recommended_actions=recommended_actions[:6],
        uncertainties=uncertainties,
        data_completeness_pct=round(avg_completeness, 1),
        sources=list(dict.fromkeys(sources)),
        rag_sources=rag_sources or [],
    )


# ── Safe serialisation ─────────────────────────────────────────────────────────

def priority_to_dict(p) -> dict:
    return {
        "title": p.title, "category": p.category, "severity": p.severity,
        "description": p.description, "evidence": p.evidence,
        "affected_campaigns": p.affected_campaigns, "affected_funnel_stage": p.affected_funnel_stage,
        "kpi_impact": p.kpi_impact, "confidence": round(p.confidence, 3),
        "data_completeness": p.data_completeness,
        "recommended_next_step": p.recommended_next_step,
        "required_approval": p.required_approval, "priority_score": p.priority_score,
        "sources": p.sources,
    }


def analysis_to_dict(a: StrategicAnalysis) -> dict:
    return {
        "tenant_id": a.tenant_id, "generated_at": a.generated_at,
        "current_situation": a.current_situation,
        "top_problems": [priority_to_dict(p) for p in a.top_problems],
        "top_opportunities": [priority_to_dict(p) for p in a.top_opportunities],
        "all_priorities": [priority_to_dict(p) for p in a.all_priorities],
        "active_objectives": a.active_objectives,
        "recommended_actions": a.recommended_actions,
        "uncertainties": a.uncertainties,
        "data_completeness_pct": a.data_completeness_pct,
        "sources": a.sources,
        "rag_sources": a.rag_sources,
    }
