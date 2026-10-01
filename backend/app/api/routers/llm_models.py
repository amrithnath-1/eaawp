"""LLM model catalogue."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import LLMModel
from app.schemas.api import LLMModelOut

router = APIRouter(prefix="/api/v1/llm-models", tags=["llm-models"])

@router.get("", response_model=list[LLMModelOut])
async def list_llm_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LLMModel).where(LLMModel.is_active == True))
    return result.scalars().all()
