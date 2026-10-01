"""
EAAWP API response/request schemas.
These are the shapes exposed at the HTTP boundary — separate from ORM models.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Company ───────────────────────────────────────────────────────────────────

class CompanyOut(BaseModel):
    id: str
    name: str
    industry: str
    region: str
    employees: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    industry: str = ""
    region: str = ""
    employees: int = 0
    description: str = ""
    website: str = ""


# ── User ──────────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: str
    role: str
    status: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3)
    name: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    role: str = "Employee"


# ── LLM Model ─────────────────────────────────────────────────────────────────

class LLMModelOut(BaseModel):
    id: str
    provider: str
    model_name: str
    display_name: str
    context_window: int
    is_active: bool

    model_config = {"from_attributes": True}


# ── AI Employee ───────────────────────────────────────────────────────────────

class AIEmployeeOut(BaseModel):
    id: str
    tenant_id: str
    role_key: str
    name: str
    status: str
    is_active: bool
    created_at: datetime
    llm_model_id: str | None = None

    model_config = {"from_attributes": True}


class AIEmployeeCreate(BaseModel):
    role_key: str
    name: str
    llm_model_id: str | None = None


# ── Agent Configuration ───────────────────────────────────────────────────────

class AgentConfigOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str
    system_persona: str
    tone: str
    autonomy_level: int
    capabilities: dict[str, bool]
    tools: dict[str, bool]
    tool_scopes: list[dict[str, Any]]
    permissions: list[dict[str, Any]]
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_json_fields(cls, data: Any) -> Any:
        if hasattr(data, "__dict__"):
            # ORM model — convert JSON strings to Python objects
            obj = dict(data.__dict__)
            obj["capabilities"] = json.loads(obj.get("capabilities_json") or "{}")
            obj["tools"] = json.loads(obj.get("tools_json") or "{}")
            obj["tool_scopes"] = json.loads(obj.get("tool_scopes_json") or "[]")
            obj["permissions"] = json.loads(obj.get("permissions_json") or "[]")
            return obj
        return data


class AgentConfigUpdate(BaseModel):
    system_persona: str | None = None
    tone: str | None = None
    autonomy_level: int | None = None
    capabilities: dict[str, bool] | None = None
    tools: dict[str, bool] | None = None
    tool_scopes: list[dict[str, Any]] | None = None
    permissions: list[dict[str, Any]] | None = None


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str
    name: str
    goal: str
    status: str
    progress: int
    department: str
    required_action: str | None
    steps: list[dict[str, Any]]
    sources: list[str]
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_json_fields(cls, data: Any) -> Any:
        if hasattr(data, "__dict__"):
            obj = dict(data.__dict__)
            obj["steps"] = json.loads(obj.get("steps_json") or "[]")
            obj["sources"] = json.loads(obj.get("sources_json") or "[]")
            return obj
        return data


class TaskCreate(BaseModel):
    name: str
    goal: str = ""
    department: str = ""
    steps: list[dict[str, Any]] = []
    sources: list[str] = []


class TaskStatusUpdate(BaseModel):
    status: str
    progress: int | None = None
    required_action: str | None = None


# ── Activity Event ────────────────────────────────────────────────────────────

class ActivityEventOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str
    kind: str
    text: str
    department: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Insight ───────────────────────────────────────────────────────────────────

class InsightOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str
    severity: str
    title: str
    detail: str
    department: str
    metric: str | None
    is_dismissed: bool
    detected_at: datetime

    model_config = {"from_attributes": True}


class InsightCreate(BaseModel):
    severity: str = "info"
    title: str
    detail: str = ""
    department: str = ""
    metric: str | None = None


# ── Schedule ──────────────────────────────────────────────────────────────────

class ScheduleOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str
    task_name: str
    frequency: str
    next_run: str
    status: str
    owner: str
    department: str

    model_config = {"from_attributes": True}


class ScheduleCreate(BaseModel):
    task_name: str
    frequency: str
    next_run: str = ""
    owner: str = ""
    department: str = ""


# ── Approval Request ──────────────────────────────────────────────────────────

class ApprovalRequestOut(BaseModel):
    id: str
    tenant_id: str
    task_id: str | None
    action: str
    detail: str
    status: str
    requested_by: str
    reviewed_by: str | None
    review_note: str | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    review_note: str | None = None
    reviewed_by: str = "human"


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: str
    tenant_id: str
    ai_employee_id: str | None
    actor: str
    event: str
    department: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
