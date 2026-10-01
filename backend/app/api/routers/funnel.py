"""EAAWP Funnel Analysis Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
from app.services.funnel_service import (
    fetch_funnel_from_external, calculate_funnel, funnel_to_dict,
)

router = APIRouter(prefix="/api/v1/funnel", tags=["funnel"])

def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


@router.post("/analyze", response_model=dict)
async def analyze_funnel_endpoint(
    body: dict,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.schemas.funnel import FUNNEL_STAGES
    concepts = body.get("concepts") or list(FUNNEL_SEMANTIC_CONCEPTS)
    invalid = [c for c in concepts if c not in FUNNEL_SEMANTIC_CONCEPTS]
    if invalid:
        raise HTTPException(400, f"Unknown funnel concepts: {invalid}")
    ext = await fetch_funnel_from_external(
        tenant_id=tenant_id, role_key="DIGITAL_MARKETING_MANAGER",
        concepts=concepts, db=db,
    )
    concept_to_stage = {
        "visitor_count": "visitors", "lead_count": "leads",
        "qualified_lead_count": "qualified_leads", "opportunity_count": "opportunities",
        "customer_count": "customers",
    }
    stage_vals = {concept_to_stage.get(k, k): v for k, v in ext.items() if k in concept_to_stage}
    funnel = calculate_funnel(
        stage_vals,
        spend=ext.get("campaign_spend"),
        revenue=ext.get("revenue"),
        period=body.get("period", ""),
        sources=[f"External: {c}" for c, v in ext.items() if v is not None],
    )
    return funnel_to_dict(funnel)


@router.post("/campaign/{campaign_id}", response_model=dict)
async def campaign_funnel_endpoint(
    campaign_id: str,
    body: dict,
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.campaign_service import get_metrics as svc_metrics
    from app.services.kpi_engine import collect_metrics, normalise_metric_name
    metric_rows = await svc_metrics(campaign_id=campaign_id, tenant_id=tenant_id, db=db)
    if not metric_rows:
        # Campaign might not be found or has no metrics
        pass
    records = [
        {"metric_name": m.metric_name, "metric_value": m.metric_value, "metric_date": m.metric_date}
        for m in metric_rows
    ]
    internal = collect_metrics(records, body.get("date_from"), body.get("date_to"))
    concept_to_stage = {
        "visitor_count": "visitors", "lead_count": "leads",
        "qualified_lead_count": "qualified_leads", "opportunity_count": "opportunities",
        "customer_count": "customers",
    }
    stage_vals: dict = {}
    for k, v in internal.items():
        nk = normalise_metric_name(k)
        if nk in ("leads", "visitors", "conversions", "customers"):
            stage_vals[nk] = v
    ext_concepts = [c for c in body.get("external_concepts", []) if c in FUNNEL_SEMANTIC_CONCEPTS]
    ext_vals: dict = {}
    if ext_concepts:
        ext_vals = await fetch_funnel_from_external(
            tenant_id=tenant_id, role_key="DIGITAL_MARKETING_MANAGER",
            concepts=ext_concepts, db=db,
        )
        for k, v in ext_vals.items():
            stage = concept_to_stage.get(k)
            if stage and v is not None and stage not in stage_vals:
                stage_vals[stage] = v
    spend = internal.get("spend") or ext_vals.get("campaign_spend")
    revenue = internal.get("revenue") or ext_vals.get("revenue")
    funnel = calculate_funnel(
        stage_vals, spend=spend, revenue=revenue,
        sources=[f"EAAWP metrics ({len(records)})", *(f"Ext:{k}" for k, v in ext_vals.items() if v is not None)],
    )
    return funnel_to_dict(funnel)
