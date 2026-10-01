"""
EAAWP Marketing Strategy Schemas

MarketingPriority, StrategicAnalysis, objective CRUD schemas.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

VALID_OBJECTIVE_TYPES = {
    "lead_generation", "conversion", "revenue", "customer_acquisition",
    "campaign_efficiency", "brand_awareness", "custom",
}
VALID_STATUSES = {"draft", "active", "achieved", "paused", "cancelled"}


# ── Objective CRUD ─────────────────────────────────────────────────────────────

class ObjectiveCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    objective_type: str = Field(default="custom", max_length=64)
    priority: int = Field(default=3, ge=1, le=5)
    target_metric: str = Field(default="", max_length=128)
    target_value: float | None = None
    start_date: str | None = None
    target_date: str | None = None
    linked_campaign_ids: list[str] = Field(default_factory=list)
    created_by: str = Field(default="agent", max_length=128)

    @field_validator("name")
    @classmethod
    def safe_name(cls, v: str) -> str:
        for bad in (";", "--", "exec(", "eval(", "DROP"):
            if bad.lower() in v.lower():
                raise ValueError(f"Name contains forbidden pattern.")
        return v.strip()

    @field_validator("objective_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in VALID_OBJECTIVE_TYPES:
            raise ValueError(f"objective_type must be one of {sorted(VALID_OBJECTIVE_TYPES)}")
        return v

    @field_validator("start_date", "target_date")
    @classmethod
    def valid_date(cls, v: str | None) -> str | None:
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date '{v}' must be YYYY-MM-DD.")
        return v


class ObjectiveUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    objective_type: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    target_metric: str | None = None
    target_value: float | None = None
    current_value: float | None = None
    start_date: str | None = None
    target_date: str | None = None
    linked_campaign_ids: list[str] | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        return v


class ObjectiveOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str
    objective_type: str
    priority: int
    status: str
    target_metric: str
    target_value: float | None
    current_value: float | None
    start_date: str | None
    target_date: str | None
    linked_campaign_ids: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Action inputs ──────────────────────────────────────────────────────────────

class CreateObjectiveInput(BaseModel):
    """Input for the create_marketing_objective action tool."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    objective_type: str = Field(default="custom")
    priority: int = Field(default=3, ge=1, le=5)
    target_metric: str = Field(default="", max_length=128)
    target_value: float | None = None
    created_by: str = Field(default="agent", max_length=128)

    @field_validator("name")
    @classmethod
    def safe_name(cls, v: str) -> str:
        for bad in (";", "--", "exec(", "eval("):
            if bad.lower() in v.lower():
                raise ValueError("Name contains forbidden pattern.")
        return v.strip()

    @field_validator("objective_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in VALID_OBJECTIVE_TYPES:
            raise ValueError(f"objective_type must be one of {sorted(VALID_OBJECTIVE_TYPES)}")
        return v


class UpdateObjectiveInput(BaseModel):
    """Input for the update_marketing_objective action tool."""
    objective_id: str = Field(..., min_length=1)
    name: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    target_value: float | None = None
    current_value: float | None = None

    @field_validator("objective_id")
    @classmethod
    def safe_id(cls, v: str) -> str:
        if not re.match(r"^[a-f0-9\-]{36}$", v):
            raise ValueError("objective_id must be a valid UUID.")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        return v


# ── Priority dataclass ─────────────────────────────────────────────────────────

@dataclass
class MarketingPriority:
    """
    A structured evidence-backed marketing priority.
    All scores are deterministic — never LLM-assigned.
    """
    title: str
    category: str           # "problem" | "opportunity" | "risk" | "monitoring_alert"
    severity: str           # "critical" | "high" | "medium" | "low"
    description: str
    evidence: list[str]     # supporting data points with values
    affected_campaigns: list[str]
    affected_funnel_stage: str
    kpi_impact: str
    confidence: float       # 0–1 based on data completeness
    data_completeness: float
    recommended_next_step: str
    required_approval: str  # "none" | "medium" | "high"
    priority_score: float   # deterministic score 0–100
    sources: list[str] = field(default_factory=list)


@dataclass
class StrategicAnalysis:
    """Complete strategic analysis output."""
    tenant_id: str
    generated_at: str
    current_situation: str
    top_problems: list[MarketingPriority]
    top_opportunities: list[MarketingPriority]
    all_priorities: list[MarketingPriority]
    active_objectives: list[dict[str, Any]]
    recommended_actions: list[str]
    uncertainties: list[str]
    data_completeness_pct: float
    sources: list[str]
    rag_sources: list[str] = field(default_factory=list)
