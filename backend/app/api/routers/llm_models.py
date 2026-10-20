"""LLM model catalogue."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import get_current_tenant_id
from app.db.session import get_db
from app.db.models import LLMModel
from app.schemas.api import LLMModelOut

router = APIRouter(prefix="/api/v1/llm-models", tags=["llm-models"])

@router.get("", response_model=list[LLMModelOut])
async def list_llm_models(
    _tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(LLMModel).where(LLMModel.is_active == True))
    return result.scalars().all()
