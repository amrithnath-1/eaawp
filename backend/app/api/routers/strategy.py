"""EAAWP Marketing Strategy Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.strategy import ObjectiveCreate, ObjectiveUpdate, ObjectiveOut
from app.services.strategy_service import (
    create_objective, list_objectives, get_objective, update_objective,
    build_strategic_analysis, analysis_to_dict,
)

from app.services.modules import require_module

router = APIRouter(prefix="/api/v1/strategy", tags=["strategy"], dependencies=[Depends(require_module("DIGITAL_MARKETING_MANAGER"))])


@router.get("/objectives", response_model=list[ObjectiveOut])
async def list_objectives_endpoint(
    status: str | None = None,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ObjectiveOut]:
    return await list_objectives(tenant_id, db, status=status)


@router.post("/objectives", response_model=ObjectiveOut, status_code=201)
async def create_objective_endpoint(
    body: ObjectiveCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ObjectiveOut:
    from app.schemas.strategy import CreateObjectiveInput
    inp = CreateObjectiveInput(**body.model_dump(exclude={"linked_campaign_ids"}))
    return await create_objective(inp, tenant_id, db)


@router.get("/objectives/{obj_id}", response_model=ObjectiveOut)
async def get_objective_endpoint(
    obj_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ObjectiveOut:
    o = await get_objective(obj_id, tenant_id, db)
    if not o:
        raise HTTPException(404, "Objective not found.")
    return o


@router.patch("/objectives/{obj_id}", response_model=ObjectiveOut)
async def update_objective_endpoint(
    obj_id: str,
    body: ObjectiveUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ObjectiveOut:
    o = await update_objective(obj_id, body, tenant_id, db)
    if not o:
        raise HTTPException(404, "Objective not found.")
    return o


@router.post("/analyze", response_model=dict)
async def analyze_strategy_endpoint(
    body: dict,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    analysis = await build_strategic_analysis(
        tenant_id=tenant_id, db=db,
        campaign_insights=body.get("campaign_insights"),
        funnel_insights=body.get("funnel_insights"),
        monitoring_anomalies=body.get("monitoring_anomalies"),
        rag_context=body.get("rag_context", ""),
        rag_sources=body.get("rag_sources"),
    )
    return analysis_to_dict(analysis)
