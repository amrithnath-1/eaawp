"""
EAAWP Controlled Action Tool Schemas

These schemas govern the action tool framework — separate from the
READ-ONLY query tool layer.

Security invariants
-------------------
- Action arguments are schema-validated before any execution attempt.
- Raw SQL, shell commands, and arbitrary HTTP are not accepted.
- The LLM cannot supply credentials; they are never part of action inputs.
- Every action must pass the governance pipeline before execution.
- Approval is enforced by risk level — the LLM cannot bypass it.

Risk levels
-----------
LOW     — may execute automatically when role config allows
MEDIUM  — configurable; default requires approval
HIGH    — always requires human approval, no exceptions
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Risk levels ───────────────────────────────────────────────────────────────

RiskLevel = Literal["low", "medium", "high"]

# Approval policy constants
ALWAYS_AUTO = "auto"        # low-risk, allowed by role config
ALWAYS_APPROVAL = "approval"  # medium/high-risk, or role config says approval
RESTRICTED = "restricted"   # role config explicitly blocks this action


# ── Action input validation ───────────────────────────────────────────────────

class CreateInternalTaskInput(BaseModel):
    """
    Input schema for the create_internal_task action.
    Creates an EAAWP-internal Task record ONLY.
    Does NOT send emails, publish content, or call external systems.
    """
    title: str = Field(..., min_length=1, max_length=255,
        description="Short descriptive title for the task.")
    description: str = Field(default="", max_length=2000,
        description="Optional detailed description of the task goal.")
    priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Task priority. Must be low, medium, or high.",
    )
    department: str = Field(default="marketing", max_length=64,
        description="Department this task belongs to.")

    @field_validator("title")
    @classmethod
    def no_sql_injection(cls, v: str) -> str:
        # Prevent any SQL/code injection in title
        forbidden = [";", "--", "/*", "*/", "xp_", "exec(", "eval("]
        for f in forbidden:
            if f.lower() in v.lower():
                raise ValueError(f"Title contains forbidden pattern '{f}'.")
        return v.strip()

    @field_validator("description")
    @classmethod
    def no_code_injection(cls, v: str) -> str:
        forbidden = ["exec(", "eval(", "subprocess", "os.system", "__import__"]
        for f in forbidden:
            if f.lower() in v.lower():
                raise ValueError(f"Description contains forbidden pattern '{f}'.")
        return v# ── Action request from LLM ───────────────────────────────────────────────────

class ActionRequest(BaseModel):
    """
    Structured action request produced by the engine from an LLM tool call.
    The LLM fills tool_name and arguments; the engine validates and routes.
    """
    tool_name: str = Field(..., min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(..., min_length=1)
    role_key: str = Field(default="DIGITAL_MARKETING_MANAGER")
    requested_by: str = Field(default="agent")   # "agent" | user ID
    session_id: str | None = None


# ── Action result ─────────────────────────────────────────────────────────────

class ActionResult(BaseModel):
    """Outcome of an action attempt — returned to the engine/LLM."""
    tool_name: str
    status: Literal[
        "proposed",          # validation passed, awaiting approval
        "approved",          # admin approved, ready to execute (or auto-executed)
        "executed",          # successfully executed
        "rejected",          # admin rejected
        "failed",            # execution attempted but failed
        "unauthorized",      # permission check failed
        "invalid_arguments", # schema validation failed
    ]
    approval_request_id: str | None = None   # present when approval is needed
    task_id: str | None = None               # present when a Task was created
    message: str = ""                        # human-readable summary
    details: dict[str, Any] = Field(default_factory=dict)


# ── Pending action record (stored in action_audit table) ─────────────────────

class ActionAuditOut(BaseModel):
    id: str
    tenant_id: str
    role_key: str
    tool_name: str
    arguments_json: str             # serialised; never contains credentials
    risk_level: str
    approval_status: str
    execution_status: str
    approval_request_id: str | None
    task_id: str | None
    error_message: str | None
    created_at: datetime
    approved_at: datetime | None
    executed_at: datetime | None

    model_config = {"from_attributes": True}


class ActionApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewed_by: str = "admin"
    review_note: str | None = None
