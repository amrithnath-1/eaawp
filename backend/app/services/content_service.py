"""
EAAWP Content Intelligence Service

All LLM generation goes through the LLM Gateway (app.llm).
Uses temperature=0.7 for content generation (intentional — more creative
variation than the default 0.0 used by engine/planner).
RAG integration uses the existing VectorStore/knowledge system.
No external publishing — generation only.
Tenant isolation enforced on every DB query.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_gateway

from app.db.content_models import ContentItem
from app.schemas.content import (
    AnalyzeContentRequest, ContentItemCreate, ContentItemOut,
    ContentItemUpdate, GenerateBriefRequest, GenerateDraftRequest,
    GenerateIdeasRequest, GenerateVariantsRequest,
)

logger = logging.getLogger(__name__)

_CONTENT_SYSTEM = (
    "You are the Marketing Intelligence Agent for a company. "
    "Your role is to help create high-quality marketing content. "
    "Always ground your content in the provided context. "
    "Do not invent company facts or metrics. "
    "Do not include credentials, database details, or internal infrastructure information. "
    "Keep responses focused, professional, and aligned with the stated objective."
)


# ── ORM helpers ────────────────────────────────────────────────────────────────

def _to_out(c: ContentItem) -> ContentItemOut:
    return ContentItemOut(
        id=c.id, tenant_id=c.tenant_id, content_type=c.content_type,
        status=c.status, title=c.title, channel=c.channel,
        brief_json=json.loads(c.brief_json or "{}"),
        body=c.body,
        campaign_id=c.campaign_id, objective_id=c.objective_id, parent_id=c.parent_id,
        rag_sources=json.loads(c.rag_sources_json or "[]"),
        analysis=json.loads(c.analysis_json or "{}"),
        metadata=json.loads(c.metadata_json or "{}"),
        created_by=c.created_by, created_at=c.created_at, updated_at=c.updated_at,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_content(body: ContentItemCreate, tenant_id: str, db: AsyncSession) -> ContentItemOut:
    item = ContentItem(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        content_type=body.content_type, status=body.status,
        title=body.title, channel=body.channel,
        brief_json=json.dumps(body.brief_json),
        body=body.body,
        campaign_id=body.campaign_id, objective_id=body.objective_id, parent_id=body.parent_id,
        rag_sources_json=json.dumps(body.rag_sources),
        metadata_json=json.dumps(body.metadata),
        created_by=body.created_by,
    )
    db.add(item)
    await db.flush()
    return _to_out(item)


async def list_content(
    tenant_id: str, db: AsyncSession,
    content_type: str | None = None, campaign_id: str | None = None, limit: int = 50
) -> list[ContentItemOut]:
    stmt = select(ContentItem).where(ContentItem.tenant_id == tenant_id)
    if content_type:
        stmt = stmt.where(ContentItem.content_type == content_type)
    if campaign_id:
        stmt = stmt.where(ContentItem.campaign_id == campaign_id)
    stmt = stmt.order_by(ContentItem.created_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return [_to_out(c) for c in result.scalars().all()]


async def get_content(content_id: str, tenant_id: str, db: AsyncSession) -> ContentItemOut | None:
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == content_id, ContentItem.tenant_id == tenant_id)
    )
    c = result.scalar_one_or_none()
    return _to_out(c) if c else None


async def update_content(content_id: str, body: ContentItemUpdate, tenant_id: str, db: AsyncSession) -> ContentItemOut | None:
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == content_id, ContentItem.tenant_id == tenant_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        return None
    if body.title is not None:
        c.title = body.title
    if body.status is not None:
        c.status = body.status
    if body.channel is not None:
        c.channel = body.channel
    if body.brief_json is not None:
        c.brief_json = json.dumps(body.brief_json)
    if body.body is not None:
        c.body = body.body
    if body.metadata is not None:
        c.metadata_json = json.dumps(body.metadata)
    await db.flush()
    return _to_out(c)


# ── RAG helper ─────────────────────────────────────────────────────────────────

async def _fetch_rag_context(tenant_id: str, query: str, db: AsyncSession) -> tuple[str, list[str]]:
    """Retrieve relevant knowledge chunks for content generation."""
    try:
        from app.config import settings
        from openai import AsyncOpenAI
        from app.services.vector_store import retrieve_similar_chunks
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        chunks = await retrieve_similar_chunks(
            query=query, tenant_id=tenant_id, role_scope="DIGITAL_MARKETING_MANAGER",
            db=db, openai_client=client, top_k=4,
        )
        if not chunks:
            return "", []
        # Enrich with document names
        from sqlalchemy import select
        from app.db.models import KnowledgeDocument
        doc_ids = list({c.document_id for c in chunks if c.document_id})
        doc_names: dict[str, str] = {}
        if doc_ids:
            result = await db.execute(
                select(KnowledgeDocument.id, KnowledgeDocument.name)
                .where(KnowledgeDocument.id.in_(doc_ids))
            )
            doc_names = {r.id: r.name for r in result.fetchall()}
        sources = []
        lines = []
        for chunk in chunks:
            name = doc_names.get(chunk.document_id, f"doc-{chunk.document_id[:8]}")
            chunk.document_name = name
            sources.append(name)
            lines.append(f"[Source: {name}]\n{chunk.text[:600]}")
        return "\n\n".join(lines), list(dict.fromkeys(sources))
    except Exception as exc:
        logger.warning("RAG fetch failed: %s", exc)
        return "", []


# ── LLM call ───────────────────────────────────────────────────────────────────

async def _llm(prompt: str, context: str = "") -> str:
    try:
        # Content generation uses temperature=0.7 for creative variation.
        # This is intentional and preserved from the original implementation.
        model = get_llm_gateway().get_chat_model(temperature=0.7)
        system = _CONTENT_SYSTEM
        if context:
            system = system + f"\n\nRelevant company knowledge:\n{context}"
        response = await model.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ])
        return response.content if isinstance(response.content, str) else ""
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        raise RuntimeError(f"Content generation failed: {exc}") from exc


# ── Generation functions ───────────────────────────────────────────────────────

async def generate_brief(req: GenerateBriefRequest, tenant_id: str, db: AsyncSession) -> ContentItemOut:
    rag_ctx, rag_sources = await _fetch_rag_context(
        tenant_id, f"brand guidelines audience {req.target_audience} {req.objective}", db
    )
    prompt = (
        f"Create a structured marketing content brief.\n\n"
        f"Objective: {req.objective}\n"
        f"Target audience: {req.target_audience or 'General'}\n"
        f"Channel: {req.channel}\n"
        f"Campaign: {req.campaign_name or 'N/A'}\n"
        f"KPIs: {', '.join(req.kpis) or 'Not specified'}\n"
        f"Tone: {req.tone}\n"
        f"Additional context: {req.additional_context or 'None'}\n\n"
        "Provide: goal, key messages (3-5 bullet points), "
        "call to action, audience pain points, and content guidelines."
    )
    body_text = await _llm(prompt, rag_ctx)
    brief_data = {
        "objective": req.objective, "target_audience": req.target_audience,
        "channel": req.channel, "tone": req.tone, "kpis": req.kpis,
    }
    create_body = ContentItemCreate(
        title=f"Brief: {req.objective[:80]}",
        content_type="brief", channel=req.channel,
        brief_json=brief_data, body=body_text,
        campaign_id=req.campaign_id, rag_sources=rag_sources,
        created_by="agent",
    )
    return await create_content(create_body, tenant_id, db)


async def generate_ideas(req: GenerateIdeasRequest, tenant_id: str, db: AsyncSession) -> ContentItemOut:
    rag_ctx, rag_sources = await _fetch_rag_context(
        tenant_id, f"content ideas {req.objective} {req.channel}", db
    )
    prompt = (
        f"Generate {req.n_ideas} creative marketing content ideas.\n\n"
        f"Objective: {req.objective}\n"
        f"Channel: {req.channel}\n"
        f"Audience: {req.target_audience or 'General'}\n\n"
        f"For each idea provide: title, format, key angle, and expected impact."
    )
    body_text = await _llm(prompt, rag_ctx)
    create_body = ContentItemCreate(
        title=f"Ideas: {req.objective[:80]}",
        content_type="idea", channel=req.channel,
        body=body_text, campaign_id=req.campaign_id,
        rag_sources=rag_sources, created_by="agent",
    )
    return await create_content(create_body, tenant_id, db)


async def generate_draft(req: GenerateDraftRequest, tenant_id: str, db: AsyncSession) -> ContentItemOut:
    rag_ctx, rag_sources = await _fetch_rag_context(
        tenant_id, f"brand voice {req.channel} content {req.objective}", db
    )
    prompt = (
        f"Write a {req.channel} marketing piece.\n\n"
        f"Objective: {req.objective}\n"
        f"Audience: {req.target_audience or 'General'}\n"
        f"Tone: {req.tone}\n"
        f"CTA: {req.cta or 'Not specified'}\n"
        f"Target length: ~{req.max_words} words\n\n"
        "Write a complete, ready-to-review draft. "
        "Do not invent facts. Base claims only on provided information."
    )
    body_text = await _llm(prompt, rag_ctx)
    create_body = ContentItemCreate(
        title=f"Draft: {req.objective[:80]}",
        content_type="draft", channel=req.channel,
        body=body_text, campaign_id=req.campaign_id,
        rag_sources=rag_sources, created_by="agent",
    )
    return await create_content(create_body, tenant_id, db)


async def generate_variants(req: GenerateVariantsRequest, tenant_id: str, db: AsyncSession) -> list[ContentItemOut]:
    source = await get_content(req.source_content_id, tenant_id, db)
    if not source:
        raise ValueError(f"Source content {req.source_content_id} not found.")

    rag_ctx, rag_sources = await _fetch_rag_context(
        tenant_id, f"variant content {source.channel}", db
    )
    variants: list[ContentItemOut] = []
    for i in range(1, req.n_variants + 1):
        prompt = (
            f"Create variant {i} of {req.n_variants} for this content:\n\n"
            f"{source.body[:2000]}\n\n"
            f"Variation instructions: {req.variation_instructions or 'Create a meaningfully different version.'}\n\n"
            "Keep the same objective but vary the approach, angle, or structure."
        )
        body_text = await _llm(prompt, rag_ctx)
        create_body = ContentItemCreate(
            title=f"Variant {i}: {source.title[:80]}",
            content_type="variant", channel=source.channel,
            body=body_text, campaign_id=source.campaign_id,
            parent_id=source.id, rag_sources=rag_sources + source.rag_sources,
            created_by="agent",
        )
        variant = await create_content(create_body, tenant_id, db)
        variants.append(variant)
    return variants


async def analyze_content(req: AnalyzeContentRequest, tenant_id: str, db: AsyncSession) -> ContentItemOut:
    item = await get_content(req.content_id, tenant_id, db)
    if not item:
        raise ValueError(f"Content {req.content_id} not found.")

    rag_ctx, rag_sources = await _fetch_rag_context(
        tenant_id, f"brand guidelines content quality {req.channel}", db
    )
    prompt = (
        f"Analyse this marketing content piece:\n\n{item.body[:3000]}\n\n"
        f"Campaign objective: {req.campaign_objective or 'Not specified'}\n"
        f"Target audience: {req.target_audience or 'Not specified'}\n"
        f"CTA: {req.cta or 'Not specified'}\n"
        f"Channel: {req.channel or item.channel}\n\n"
        "Provide: clarity score (1-10), audience alignment, CTA strength, "
        "top 3 strengths, top 3 improvement areas, and specific recommended rewrites."
    )
    analysis_text = await _llm(prompt, rag_ctx)
    analysis_data = {"analysis": analysis_text, "analysed_at": datetime.now(timezone.utc).isoformat()}

    # Update the content item with analysis
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == item.id, ContentItem.tenant_id == tenant_id)
    )
    c = result.scalar_one_or_none()
    if c:
        existing = json.loads(c.analysis_json or "{}")
        existing.update(analysis_data)
        c.analysis_json = json.dumps(existing)
        existing_sources = json.loads(c.rag_sources_json or "[]")
        combined = list(dict.fromkeys(existing_sources + rag_sources))
        c.rag_sources_json = json.dumps(combined)
        await db.flush()
        return _to_out(c)
    return item
