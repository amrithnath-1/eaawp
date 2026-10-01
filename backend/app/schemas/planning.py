"""
EAAWP Agent Planning Schemas

Structured plan representation for multi-step agent execution.

Security invariants
-------------------
- Plans store safe execution metadata only.
- Chain-of-thought / reasoning text is NEVER persisted.
- Credentials, connection strings, and secrets are never in plan storage.
- Tenant isolation applies to all plan records.

Step types
----------
read        — query tool (query_company_data, fetch_knowledge_base, etc.)
action      — action tool (create_internal_task, etc.)
analysis    — internal reasoning based on prior results (no tool call)
verify      — check a prior action actually produced the expected result
response    — synthesise the final response to the user

Step statuses
-------------
pending           — not yet started
running           — currently executing
completed         — finished successfully
failed            — tool returned an error or verification failed
awaiting_approval — action requires human approval before proceeding
approved          — approval received, ready to execute
rejected          — action was rejected, dependent steps blocked
skipped           — blocked by a failed/rejected dependency
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_PLAN_STEPS = 10          # maximum steps in a single plan
MAX_TOOL_CALLS_PER_PLAN = 8  # maximum tool invocations (prevents infinite loops)

PlanStatus = Literal[
    "planning",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "rejected",
]

StepType = Literal["read", "action", "analysis", "verify", "response"]

StepStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "awaiting_approval",
    "approved",
    "rejected",
    "skipped",
]


# ── Plan step ─────────────────────────────────────────────────────────────────

class PlanStepOut(BaseModel):
    """A single step in an execution plan — as returned from the API."""
    step_id: str
    plan_id: str
    step_index: int
    step_type: StepType
    description: str              # what this step does (safe, user-visible)
    tool_name: str | None         # tool to invoke, if any
    arguments_json: str           # safe structured args (no credentials)
    depends_on: list[int]         # step indices this step depends on
    status: StepStatus
    result_summary: str           # short safe result description (no secrets)
    approval_request_id: str | None
    action_audit_id: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ── Execution plan ────────────────────────────────────────────────────────────

class ExecutionPlanOut(BaseModel):
    """Full execution plan record — as returned from the API."""
    id: str
    tenant_id: str
    role_key: str
    session_id: str | None
    objective: str                # user's original request (safe to display)
    status: PlanStatus
    total_steps: int
    completed_steps: int
    tool_calls_used: int
    final_message: str            # agent's final response to user
    error_message: str | None
    steps: list[PlanStepOut]
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ── Plan resume request ───────────────────────────────────────────────────────

class PlanResumeRequest(BaseModel):
    """
    Request to resume a plan after an action was approved.
    Revalidates tenant, role, and blueprint permissions before resuming.
    """
    plan_id: str
    reviewed_by: str = "admin"


# ── Internal planning structures (not persisted) ──────────────────────────────

class PlannedStep(BaseModel):
    """Internal representation of a step during LLM planning — never persisted."""
    step_index: int
    step_type: StepType
    description: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)


class AgentPlan(BaseModel):
    """LLM-generated execution plan — internal use only, never returned to client."""
    objective: str
    steps: list[PlannedStep]
    reasoning_summary: str = ""   # brief public summary (NOT chain-of-thought)
