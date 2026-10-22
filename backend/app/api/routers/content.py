"""EAAWP Content Intelligence Router"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.content import (
    ContentItemCreate, ContentItemUpdate, ContentItemOut,
    GenerateBriefRequest, GenerateIdeasRequest,
    GenerateDraftRequest, GenerateVariantsRequest, AnalyzeContentRequest,
)
from app.services.content_service import (
    create_content, list_content, get_content, update_content,
    generate_brief, generate_ideas, generate_draft,
    generate_variants, analyze_content,
)

from app.services.modules import require_module

router = APIRouter(prefix="/api/v1/content", tags=["content"], dependencies=[Depends(require_module("DIGITAL_MARKETING_MANAGER"))])


@router.get("", response_model=list[ContentItemOut])
async def list_content_ep(
    content_type: str | None = None,
    campaign_id: str | None = None,
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ContentItemOut]:
    return await list_content(tenant_id, db, content_type=content_type,
                              campaign_id=campaign_id, limit=limit)


@router.post("", response_model=ContentItemOut, status_code=201)
async def create_content_ep(
    body: ContentItemCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    return await create_content(body, tenant_id, db)


@router.get("/{content_id}", response_model=ContentItemOut)
async def get_content_ep(
    content_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    item = await get_content(content_id, tenant_id, db)
    if not item:
        raise HTTPException(404, "Content not found.")
    return item


@router.patch("/{content_id}", response_model=ContentItemOut)
async def update_content_ep(
    content_id: str,
    body: ContentItemUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    item = await update_content(content_id, body, tenant_id, db)
    if not item:
        raise HTTPException(404, "Content not found.")
    return item


@router.post("/generate/brief", response_model=ContentItemOut, status_code=201)
async def generate_brief_ep(
    body: GenerateBriefRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    return await generate_brief(body, tenant_id, db)


@router.post("/generate/ideas", response_model=ContentItemOut, status_code=201)
async def generate_ideas_ep(
    body: GenerateIdeasRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    return await generate_ideas(body, tenant_id, db)


@router.post("/generate/draft", response_model=ContentItemOut, status_code=201)
async def generate_draft_ep(
    body: GenerateDraftRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    return await generate_draft(body, tenant_id, db)


@router.post("/generate/variants", response_model=list[ContentItemOut], status_code=201)
async def generate_variants_ep(
    body: GenerateVariantsRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ContentItemOut]:
    try:
        return await generate_variants(body, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/analyze", response_model=ContentItemOut)
async def analyze_content_ep(
    body: AnalyzeContentRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ContentItemOut:
    try:
        return await analyze_content(body, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
