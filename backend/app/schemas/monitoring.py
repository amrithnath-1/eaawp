"""
EAAWP Monitoring Rule Schemas

Structured, validated schemas for the Autonomous Monitoring and Trigger Engine.

Security invariants
-------------------
- Conditions are structured (metric + operator + threshold) — no arbitrary SQL,
  no arbitrary Python expressions, no arbitrary HTTP requests.
- Monitoring rules belong to a specific tenant + role_key pair.
- Rules only operate on semantic concepts the role is authorised to access.
- All evaluation results are audited safely (no row-level data, no credentials).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Allowed condition operators ───────────────────────────────────────────────

ALLOWED_METRIC_OPERATORS: set[str] = {
    "decreases_by_more_than_pct",    # relative decrease in %
    "increases_by_more_than_pct",    # relative increase in %
    "falls_below",                   # absolute threshold
    "exceeds",                       # absolute threshold
    "equals",                        # exact equality
    "is_unavailable",                # data unavailable / empty result
    "count_falls_below",             # row count below threshold
    "count_exceeds",                 # row count above threshold
}

# ── Allowed evaluation frequencies ───────────────────────────────────────────

# Minimum granularity: once per hour.
ALLOWED_FREQUENCIES: set[str] = {
    "hourly",       # every 60 minutes
    "every_6h",     # every 6 hours
    "daily",        # once per day (at a sensible time)
}

FREQUENCY_INTERVAL_MINUTES: dict[str, int] = {
    "hourly": 60,
    "every_6h": 360,
    "daily": 1440,
}

# ── Condition model ───────────────────────────────────────────────────────────

class MonitoringCondition(BaseModel):
    """
    A structured, validated condition.

    Examples
    --------
    clicks decrease by more than 20%:
        metric_field  = "clicks"
        operator      = "decreases_by_more_than_pct"
        threshold     = 20.0
        comparison_window_hours = 168   # compare against prior week

    spend exceeds 10000:
        metric_field  = "spend"
        operator      = "exceeds"
        threshold     = 10000.0

    conversion_rate falls below 0.02:
        metric_field  = "conversion_rate"
        operator      = "falls_below"
        threshold     = 0.02

    data becomes unavailable:
        metric_field  = ""
        operator      = "is_unavailable"
        threshold     = 0.0

    No arbitrary SQL, code, or external requests are accepted.
    """

    metric_field: str = Field(
        "",
        max_length=128,
        description="The field/column name to aggregate and compare. "
                    "Must match a field in the semantic mapping.",
    )
    operator: str = Field(
        ...,
        description=f"Comparison operator. One of: {sorted(ALLOWED_METRIC_OPERATORS)}",
    )
    threshold: float = Field(
        0.0,
        description="Numeric threshold value.",
    )
    # For relative operators (pct-based), how far back to compare against
    comparison_window_hours: int = Field(
        24,
        ge=1,
        le=720,  # max 30 days
        description="Look-back window in hours for relative comparisons.",
    )
    # Aggregation function for numeric fields
    aggregate_fn: Literal["avg", "sum", "count", "max", "min", "latest"] = Field(
        "avg",
        description="Aggregation to apply before comparison.",
    )

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in ALLOWED_METRIC_OPERATORS:
            raise ValueError(
                f"Operator '{v}' is not allowed. "
                f"Must be one of: {sorted(ALLOWED_METRIC_OPERATORS)}"
            )
        return v

    @field_validator("metric_field")
    @classmethod
    def validate_metric_field(cls, v: str) -> str:
        # Must be a safe identifier — no spaces, no SQL keywords, no injections
        import re
        if v and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError(
                f"metric_field '{v}' is not a valid identifier. "
                "Use only letters, digits, and underscores."
            )
        return v


# ── Monitoring Rule schemas ───────────────────────────────────────────────────

class MonitoringRuleCreate(BaseModel):
    """Request body for creating a new monitoring rule."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=1000)
    enabled: bool = Field(True)

    # Scope — what data to monitor
    semantic_concept: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="The semantic concept (data source) to monitor. "
                    "Must have a semantic mapping configured for this tenant.",
    )

    # Structured condition — no arbitrary code
    condition: MonitoringCondition

    # How often to evaluate
    evaluation_frequency: str = Field(
        "daily",
        description=f"How often to evaluate. One of: {sorted(ALLOWED_FREQUENCIES)}",
    )

    # What to do when condition triggers
    action_objective: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The objective to pass to the planning engine when triggered. "
                    "This becomes the user-visible task description.",
    )

    # Approval governance
    require_approval_on_trigger: bool = Field(
        False,
        description="If True, any plan created on trigger will require human approval "
                    "before execution (same as setting the action tool as guarded).",
    )

    # Deduplication / cooldown — prevent flooding plans
    cooldown_hours: int = Field(
        24,
        ge=1,
        le=720,
        description="Minimum hours between triggered plans for this rule. "
                    "Prevents duplicate plans while condition persists.",
    )

    @field_validator("evaluation_frequency")
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        if v not in ALLOWED_FREQUENCIES:
            raise ValueError(
                f"evaluation_frequency '{v}' is not allowed. "
                f"Must be one of: {sorted(ALLOWED_FREQUENCIES)}"
            )
        return v


class MonitoringRuleOut(BaseModel):
    """A monitoring rule as returned from the API."""

    id: str
    tenant_id: str
    role_key: str
    name: str
    description: str
    enabled: bool
    semantic_concept: str
    condition: MonitoringCondition
    evaluation_frequency: str
    action_objective: str
    require_approval_on_trigger: bool
    cooldown_hours: int
    # Timestamps
    last_evaluated_at: datetime | None
    last_triggered_at: datetime | None
    next_evaluation_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Operational state
    status: str  # "idle" | "evaluating" | "triggered" | "error" | "disabled"
    last_evaluation_result: str | None   # "condition_false" | "condition_true" | "error" | "permission_denied" | "no_data"
    last_error_message: str | None       # safe error text, no credentials
    last_triggered_plan_id: str | None

    model_config = {"from_attributes": True}


class MonitoringRuleUpdate(BaseModel):
    """Partial update for a monitoring rule."""

    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    semantic_concept: str | None = None
    condition: MonitoringCondition | None = None
    evaluation_frequency: str | None = None
    action_objective: str | None = None
    require_approval_on_trigger: bool | None = None
    cooldown_hours: int | None = None

    @field_validator("evaluation_frequency")
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_FREQUENCIES:
            raise ValueError(
                f"evaluation_frequency '{v}' is not allowed. "
                f"Must be one of: {sorted(ALLOWED_FREQUENCIES)}"
            )
        return v


# ── Monitoring Evaluation Audit schema ────────────────────────────────────────

class MonitoringAuditOut(BaseModel):
    """
    Safe audit record for a single monitoring rule evaluation.
    Never stores credentials, raw SQL, secrets, or row-level company data.
    """

    id: str
    tenant_id: str
    role_key: str
    rule_id: str
    rule_name: str
    evaluated_at: datetime
    semantic_concept: str
    # Safe result — no actual data values stored
    result: str          # "condition_false" | "condition_true" | "error" | "permission_denied" | "no_data"
    triggered: bool
    triggered_plan_id: str | None
    failure_reason: str | None  # safe error message only, no credentials/SQL/secrets
    # Aggregate metrics used (safe — just the computed aggregate value, not raw rows)
    current_value: float | None
    previous_value: float | None

    model_config = {"from_attributes": True}


# ── NL-config integration schemas ─────────────────────────────────────────────

class NLMonitoringRuleProposal(BaseModel):
    """
    Structured monitoring rule proposal produced by the NL configuration interpreter.
    This is validated before being shown to the administrator for approval.
    """

    name: str
    description: str
    semantic_concept: str
    condition: MonitoringCondition
    evaluation_frequency: str
    action_objective: str
    require_approval_on_trigger: bool = False
    cooldown_hours: int = 24

    @field_validator("evaluation_frequency")
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        if v not in ALLOWED_FREQUENCIES:
            raise ValueError(
                f"evaluation_frequency '{v}' is not allowed. "
                f"Must be one of: {sorted(ALLOWED_FREQUENCIES)}"
            )
        return v
