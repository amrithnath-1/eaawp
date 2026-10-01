"""
EAAWP Campaign Schemas

Pydantic v2 schemas for the Campaign Management subsystem.

Security invariants
-------------------
- No raw SQL accepted in any field.
- No external database credentials or connection details.
- Tenant isolation enforced at every layer.
- Budget changes require HIGH-risk governance.
- Status transitions to active/cancelled require approval.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Status ────────────────────────────────────────────────────────────────────

CampaignStatus = Literal[
    "draft", "planned", "active", "paused", "completed", "cancelled"
]

VALID_STATUSES = {"draft", "planned", "active", "paused", "completed", "cancelled"}

# Status transitions that require HIGH-risk approval
HIGH_RISK_TRANSITIONS = {
    ("planned", "active"),
    ("paused", "active"),
    ("active", "cancelled"),
}

# Statuses treated as HIGH risk when a budget change is also present
BUDGET_CHANGE_RISK = "high"

# ── KPI definition ────────────────────────────────────────────────────────────

class KPIDefinition(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target: float = Field(default=0.0)
    unit: str = Field(default="", max_length=32)


# ── Campaign Create ───────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=5000)
    target_audience: str = Field(default="", max_length=1000)
    channel: str = Field(default="", max_length=128)
    budget: float = Field(default=0.0, ge=0.0)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    kpis: list[KPIDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(default="agent", max_length=128)

    @field_validator("name")
    @classmethod
    def no_sql_injection(cls, v: str) -> str:
        forbidden = [";", "--", "/*", "*/", "xp_", "exec(", "eval("]
        for f in forbidden:
            if f.lower() in v.lower():
                raise ValueError(f"Name contains forbidden pattern '{f}'.")
        return v.strip()

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date '{v}' must be in YYYY-MM-DD format.")
        return v

    @field_validator("channel")
    @classmethod
    def safe_channel(cls, v: str) -> str:
        # Channel is a label — no SQL keywords
        forbidden = [";", "--", "DROP", "SELECT", "INSERT"]
        for f in forbidden:
            if f.upper() in v.upper():
                raise ValueError(f"Channel contains forbidden pattern '{f}'.")
        return v


# ── Campaign Update ───────────────────────────────────────────────────────────

class CampaignUpdate(BaseModel):
    """Partial update. Status + budget changes may trigger governance."""
    name: str | None = Field(default=None, max_length=255)
    objective: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=5000)
    target_audience: str | None = Field(default=None, max_length=1000)
    channel: str | None = Field(default=None, max_length=128)
    budget: float | None = Field(default=None, ge=0.0)
    start_date: str | None = None
    end_date: str | None = None
    status: CampaignStatus | None = None
    kpis: list[KPIDefinition] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date '{v}' must be in YYYY-MM-DD format.")
        return v


def determine_update_risk(
    update: CampaignUpdate,
    current_status: str,
    current_budget: float,
) -> str:
    """
    Determine the risk level for a campaign update.
    Returns "low", "medium", or "high".
    """
    # Budget change is HIGH risk
    if update.budget is not None and update.budget != current_budget:
        return "high"

    # HIGH-risk status transitions
    if update.status is not None:
        transition = (current_status, update.status)
        if transition in HIGH_RISK_TRANSITIONS:
            return "high"
        if update.status in ("cancelled",):
            return "high"

    # Any other update is MEDIUM risk
    if any(v is not None for v in [
        update.name, update.objective, update.description,
        update.target_audience, update.channel, update.start_date,
        update.end_date, update.kpis, update.metadata,
    ]):
        return "medium"

    return "low"


# ── Campaign Output ───────────────────────────────────────────────────────────

class CampaignOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    objective: str
    description: str
    status: str
    target_audience: str
    channel: str
    budget: float
    start_date: str | None
    end_date: str | None
    kpis: list[KPIDefinition]
    metadata: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Campaign Metric schemas ───────────────────────────────────────────────────

class CampaignMetricCreate(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=128)
    metric_value: float
    metric_date: str = Field(..., description="YYYY-MM-DD format")
    source: str = Field(default="manual", max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_by: str = Field(default="agent", max_length=128)

    @field_validator("metric_name")
    @classmethod
    def safe_metric_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\- ]{1,128}$", v):
            raise ValueError(f"metric_name '{v}' contains invalid characters.")
        return v.strip()

    @field_validator("metric_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"metric_date '{v}' must be YYYY-MM-DD.")
        return v


class CampaignMetricOut(BaseModel):
    id: str
    campaign_id: str
    tenant_id: str
    metric_name: str
    metric_value: float
    metric_date: str
    source: str
    metadata: dict[str, Any]
    recorded_by: str
    recorded_at: datetime

    model_config = {"from_attributes": True}


# ── Campaign summary ──────────────────────────────────────────────────────────

class CampaignSummary(BaseModel):
    """Safe high-level summary for LLM consumption — no credentials."""
    id: str
    name: str
    status: str
    channel: str
    objective: str
    budget: float
    start_date: str | None
    end_date: str | None
    kpi_count: int
    metric_count: int
    latest_metrics: list[dict[str, Any]]


# ── Action input schemas (for ACTION_REGISTRY) ────────────────────────────────

class CreateCampaignInput(BaseModel):
    """Input for the create_campaign action tool."""
    name: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(default="", max_length=2000)
    channel: str = Field(default="", max_length=128)
    budget: float = Field(default=0.0, ge=0.0)
    target_audience: str = Field(default="", max_length=1000)
    start_date: str | None = None
    end_date: str | None = None
    kpis: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def no_injection(cls, v: str) -> str:
        forbidden = [";", "--", "/*", "*/", "xp_", "exec(", "eval("]
        for f in forbidden:
            if f.lower() in v.lower():
                raise ValueError(f"Name contains forbidden pattern.")
        return v.strip()


class UpdateCampaignInput(BaseModel):
    """Input for the update_campaign action tool."""
    campaign_id: str = Field(..., min_length=1)
    name: str | None = None
    objective: str | None = None
    channel: str | None = None
    budget: float | None = Field(default=None, ge=0.0)
    status: str | None = None
    target_audience: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"status '{v}' is not valid. Use: {sorted(VALID_STATUSES)}")
        return v

    @field_validator("campaign_id")
    @classmethod
    def safe_id(cls, v: str) -> str:
        if not re.match(r"^[a-f0-9\-]{36}$", v):
            raise ValueError("campaign_id must be a valid UUID.")
        return v
