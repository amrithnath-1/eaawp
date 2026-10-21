"""Agent configuration router."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import AgentConfiguration
from app.schemas.api import AgentConfigOut, AgentConfigUpdate

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

@router.get("/config", response_model=AgentConfigOut)
async def get_agent_config(
    ai_employee_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentConfiguration).where(
            AgentConfiguration.ai_employee_id == ai_employee_id,
            AgentConfiguration.tenant_id == tenant_id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Agent configuration not found")
    return cfg

@router.patch("/config", response_model=AgentConfigOut, dependencies=[Depends(require_admin)])
async def update_agent_config(
    ai_employee_id: str,
    body: AgentConfigUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentConfiguration).where(
            AgentConfiguration.ai_employee_id == ai_employee_id,
            AgentConfiguration.tenant_id == tenant_id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Agent configuration not found")

    if body.system_persona is not None:
        cfg.system_persona = body.system_persona
    if body.tone is not None:
        cfg.tone = body.tone
    if body.autonomy_level is not None:
        cfg.autonomy_level = body.autonomy_level
    if body.capabilities is not None:
        cfg.capabilities_json = json.dumps(body.capabilities)
    if body.tools is not None:
        cfg.tools_json = json.dumps(body.tools)
    if body.tool_scopes is not None:
        cfg.tool_scopes_json = json.dumps(body.tool_scopes)
    if body.permissions is not None:
        cfg.permissions_json = json.dumps(body.permissions)

    await db.commit()
    await db.refresh(cfg)
    return cfg
