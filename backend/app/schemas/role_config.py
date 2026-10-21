"""
EAAWP Role Configuration Schemas

These are the HTTP boundary schemas for the Role Configuration layer.
They sit BETWEEN company/user intent and the AgentBlueprint — the role
configuration is the persistent, editable form; the blueprint is the
validated execution form derived from it.

Role Configuration → (build_blueprint) → AgentBlueprint → DynamicAgentEngine
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Allowed role keys ─────────────────────────────────────────────────────────

RoleKey = Literal[
    "DIGITAL_MARKETING_MANAGER",
    "SALES_DEVELOPMENT_REP",
    "FINANCIAL_ANALYST",
    "HR_BUSINESS_PARTNER",
    "CUSTOMER_SUCCESS_MANAGER",
    "OPERATIONS_ANALYST",
    "DATA_INTELLIGENCE_ANALYST",
    "INSTITUTIONAL_CLERK",
]

# Roles that are active; all others return 404/coming-soon.
IMPLEMENTED_ROLES: set[str] = {"DIGITAL_MARKETING_MANAGER", "DATA_INTELLIGENCE_ANALYST", "INSTITUTIONAL_CLERK"}


# ── Sub-models ────────────────────────────────────────────────────────────────

class ToolScopeEntry(BaseModel):
    """A single tool's governance configuration within a role."""
    name: str = Field(..., min_length=1)
    tool_key: str = Field(..., min_length=1, description="Key in MASTER_TOOL_REGISTRY")
    governance: Literal["enabled", "requires_approval", "disabled"] = "enabled"
    description: str = ""


class WorkflowEntry(BaseModel):
    """A named workflow this agent can trigger."""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    trigger: str = ""           # e.g. "scheduled", "manual", "event"
    enabled: bool = True


class MonitoringRule(BaseModel):
    """A monitoring rule that fires when a condition is met."""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    condition: str = ""
    action: str = ""
    enabled: bool = True


class ApprovalRule(BaseModel):
    """Defines when human approval is required before an action executes."""
    action: str = Field(..., min_length=1)
    mode: Literal["auto", "approval", "restricted"] = "approval"


class SchedulePreference(BaseModel):
    """When this role's recurring tasks should run."""
    task: str = Field(..., min_length=1)
    frequency: str = ""           # e.g. "Every Monday 07:00"
    enabled: bool = True


class MemorySettings(BaseModel):
    """Controls how much context/history the agent retains."""
    conversation_window: int = Field(default=10, ge=1, le=100,
        description="Number of previous turns to include in context")
    retain_tool_results: bool = True
    summarise_after_turns: int = Field(default=20, ge=5, le=200)


# ── Main configuration model ──────────────────────────────────────────────────

class RoleConfigOut(BaseModel):
    """
    Full role configuration as returned from the API.
    This is the canonical representation a frontend or orchestrator reads.
    """
    id: str
    tenant_id: str
    role_key: str
    role_name: str
    agent_name: str
    description: str
    responsibilities: list[str]
    objectives: list[str]
    instructions: str                   # free-text system-persona addendum
    system_persona: str                 # full compiled system message
    allowed_tools: list[str]            # tool_key values with governance == "enabled"
    guarded_tools: list[str]            # tool_key values with governance == "requires_approval"
    tool_scopes: list[ToolScopeEntry]
    capabilities: dict[str, bool]
    permissions: list[ApprovalRule]
    workflows: list[WorkflowEntry]
    monitoring_rules: list[MonitoringRule]
    communication_style: str            # e.g. "Concise", "Formal", "Consultative"
    schedule_preferences: list[SchedulePreference]
    memory_settings: MemorySettings
    llm_model: str                      # e.g. "gpt-4o-mini"
    autonomy_level: int
    quick_prompts: list[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleConfigUpdate(BaseModel):
    """
    Partial update payload — every field is optional.
    The backend merges supplied fields with the stored configuration.
    """
    role_name: str | None = None
    agent_name: str | None = None
    description: str | None = None
    responsibilities: list[str] | None = None
    objectives: list[str] | None = None
    instructions: str | None = None
    tool_scopes: list[ToolScopeEntry] | None = None
    capabilities: dict[str, bool] | None = None
    permissions: list[ApprovalRule] | None = None
    workflows: list[WorkflowEntry] | None = None
    monitoring_rules: list[MonitoringRule] | None = None
    communication_style: str | None = None
    schedule_preferences: list[SchedulePreference] | None = None
    memory_settings: MemorySettings | None = None
    llm_model: str | None = None
    autonomy_level: int | None = Field(default=None, ge=1, le=4)
    quick_prompts: list[str] | None = None

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Keep in sync with ALLOWED_MODELS in app/llm/config.py.
        allowed = {
            # OpenAI
            "gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo",
            # Google Gemini
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-preview-04-17",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        }
        if v not in allowed:
            raise ValueError(f"llm_model must be one of {sorted(allowed)}")
        return v


class RoleConfigValidationResult(BaseModel):
    """Result of validating a role configuration."""
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    allowed_tools: list[str] = []
    guarded_tools: list[str] = []
    unrecognised_tools: list[str] = []


class ActiveBlueprintResponse(BaseModel):
    """
    Returns the AgentBlueprint that would be passed to DynamicAgentEngine
    for the current role configuration.  Useful for preview / debugging.
    """
    role_key: str
    agent_id: str
    role_name: str
    system_persona: str
    allowed_tools: list[str]
    guarded_tools: list[str]
    tenant_id: str
    llm_model: str


class RoleComingSoon(BaseModel):
    """Returned for role keys that are reserved but not yet implemented."""
    role_key: str
    status: Literal["coming_soon"] = "coming_soon"
    message: str = "This role is not yet available. Check back in a future release."
