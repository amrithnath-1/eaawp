"""AI employee workspace selection: which role the signed-in person works with (see app/services/workspaces.py)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import workspaces as ws

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


class ToolOut(BaseModel):
    name: str
    requires_approval: bool


class RoleCardOut(BaseModel):
    key: str
    name: str
    purpose: str
    capabilities: list[str]
    knowledge_domain: str
    main_tools: list[ToolOut]
    available: bool
    unavailable_reason: str | None = None


class SelectedOut(BaseModel):
    role_key: str
    name: str
    source: str
    selected_at: datetime | None = None


class AiContextOut(BaseModel):
    role_key: str
    role_name: str
    agent_name: str
    allowed_tools: list[str]
    guarded_tools: list[str]
    quick_prompts: list[str]
    knowledge_scope: str
    knowledge_domain: str
    safety_rules: list[str]


class WorkspaceStateOut(BaseModel):
    needs_selection: bool
    notice: str | None = None
    can_switch: bool
    roles: list[RoleCardOut]
    selected: SelectedOut | None = None
    navigation: list[str]
    ai: AiContextOut | None = None


class SelectBody(BaseModel):
    role_key: str = Field(..., min_length=1, max_length=128)


@router.get("", response_model=WorkspaceStateOut)
async def get_workspace(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await ws.workspace_state(db, user)


@router.put("", response_model=WorkspaceStateOut)
async def select_workspace(body: SelectBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await ws.select_workspace(db, user, body.role_key)


@router.get("/tools")
async def workspace_tools(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The selected AI employee's tools with their real status, pending approvals and recent operations."""
    from app.services.tool_status import tool_status
    return await tool_status(db, user)
