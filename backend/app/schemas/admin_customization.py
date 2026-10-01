"""
EAAWP Admin AI Customization Schemas.

These schemas represent the structured output of the Admin AI Customization
service. The LLM proposes a plan; the backend validates every field; the
admin confirms; the backend executes through existing services.

Security invariants:
- The LLM never receives credentials, API keys, or OAuth tokens.
- The LLM can only propose — the backend validates and executes.
- Each operation type maps exactly to an existing EAAWP service function.
- No credentials ever appear in the plan, request, or response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Allowed operation types ──────────────────────────────────────────────────

OperationType = Literal[
    "CREATE_AI_EMPLOYEE",
    "UPDATE_AI_EMPLOYEE",
    "CONNECT_INTEGRATION",
    "GRANT_CAPABILITY",
    "REVOKE_CAPABILITY",
    "CREATE_WORKFLOW",
    "UPDATE_WORKFLOW",
    "SET_APPROVAL_POLICY",
]


class CustomizationOperation(BaseModel):
    """One structured operation within a customization plan."""

    type: OperationType
    description: str = Field(..., max_length=500, description="Human-readable description shown to admin")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured parameters for this operation. Never contains credentials.",
    )
    requires_confirmation: bool = True
    order: int = Field(default=0, ge=0, description="Execution order within the plan")

    @field_validator("params")
    @classmethod
    def params_no_credentials(cls, v: dict) -> dict:
        """Block credential-like keys from appearing in operation params."""
        forbidden = {
            "password", "passwd", "api_key", "access_token", "refresh_token",
            "client_secret", "secret", "token", "credential", "credentials",
            "private_key", "auth", "authorization", "bearer",
        }
        for key in v:
            if key.lower() in forbidden:
                raise ValueError(
                    f"Operation params must not contain credential field '{key}'. "
                    "Credentials are handled separately by secure credential flows."
                )
        return v


class CustomizationPlan(BaseModel):
    """
    Structured customization plan returned by the LLM and validated by the backend.
    Must be confirmed by the admin before execution.
    """

    summary: str = Field(..., max_length=1000, description="Human-readable summary of all changes")
    operations: list[CustomizationOperation] = Field(
        default_factory=list,
        description="Ordered list of operations to execute",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Information needed from the admin before proceeding",
    )
    requires_confirmation: bool = Field(
        default=True,
        description="Always True for plans with operations",
    )

    @field_validator("operations")
    @classmethod
    def max_operations(cls, v: list) -> list:
        if len(v) > 20:
            raise ValueError("A customization plan cannot have more than 20 operations")
        return v


class AdminCustomizationRequest(BaseModel):
    """Admin natural-language customization request."""

    instruction: str = Field(..., min_length=1, max_length=3000)
    requested_by: str = Field(default="admin", max_length=128)


class AdminCustomizationConfirmRequest(BaseModel):
    """Admin confirmation to execute a previously generated plan."""

    plan: CustomizationPlan
    confirmed_by: str = Field(..., min_length=1, max_length=128)


class OperationResult(BaseModel):
    """Result of executing one operation."""

    type: OperationType
    description: str
    status: Literal["success", "failed", "skipped"]
    detail: str = ""
    created_id: str | None = None  # ID of created resource, if applicable


class AdminCustomizationResult(BaseModel):
    """Result of executing a confirmed customization plan."""

    plan_summary: str
    operations_total: int
    operations_succeeded: int
    operations_failed: int
    results: list[OperationResult]
    executed_at: datetime
    executed_by: str
    audit_id: str
