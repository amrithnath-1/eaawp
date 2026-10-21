"""
EAAWP Phase H — AI Employee Builder Schemas.

These schemas represent the structured output of parsing a natural-language
employee creation request. The LLM proposes; the backend validates and acts.

Security invariants:
- The LLM cannot set credentials, tenant_id, or bypass governance.
- Blueprint proposals require explicit human approval.
- capability_requirements lists what is needed — not what is granted.
  Grants are created separately after the user approves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EmployeeStatus = Literal[
    "DRAFT", "PENDING_APPROVAL", "ACTIVE", "PAUSED", "DISABLED", "ARCHIVED"
]


class RequiredCapability(BaseModel):
    """A capability required for an employee to perform its function."""
    provider_type: str
    capability_key: str
    reason: str = ""
    is_available: bool = False
    integration_id: str | None = None


class MissingIntegration(BaseModel):
    """An integration that needs to be connected for the employee to function."""
    provider_type: str
    display_name: str
    reason: str
    required_capabilities: list[str] = Field(default_factory=list)


class EmployeeBlueprintProposal(BaseModel):
    """
    LLM-generated proposal for a new AI employee.
    Must go through human approval before the employee is created.
    """
    id: str
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    role_key: str = Field(..., description="Role key, e.g. 'COMPETITOR_ANALYST'")
    purpose: str = Field(..., min_length=1, max_length=1000)
    responsibilities: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    required_capabilities: list[RequiredCapability] = Field(default_factory=list)
    missing_integrations: list[MissingIntegration] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    guarded_tools: list[str] = Field(default_factory=list)
    suggested_schedule: str | None = None
    communication_style: str = "Concise"
    llm_model: str = "gpt-4o-mini"
    system_persona: str = ""
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    created_by: str = "admin"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    review_note: str | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)


class EmployeeBlueprintRequest(BaseModel):
    """Natural-language employee creation request."""
    instruction: str = Field(..., min_length=1, max_length=2000)
    requested_by: str = Field(default="admin", max_length=128)


class EmployeeBlueprintDecision(BaseModel):
    """Approve or reject an employee blueprint proposal."""
    decision: Literal["approve", "reject"]
    reviewed_by: str = Field(default="", max_length=128)  # ignored: the reviewer is always the authenticated admin
    review_note: str = Field(default="", max_length=1000)


class EmployeeOut(BaseModel):
    """Safe output schema for an AI employee — no credentials."""
    id: str
    tenant_id: str
    role_key: str
    name: str
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
