"""
EAAWP Natural-Language Configuration Interpreter Schemas

These schemas represent the proposal lifecycle for natural-language
configuration changes.

Security contract
-----------------
The LLM NEVER modifies configuration directly. It only produces a
structured ConfigChangePatch (a subset of RoleConfigUpdate). The patch
is validated against MASTER_TOOL_REGISTRY and existing permissions
before being shown to the administrator. Only after explicit approval
is the patch applied via the existing PATCH /api/v1/roles/{role_key}.

No tool permission can be escalated to "enabled" for a tool that is not
in MASTER_TOOL_REGISTRY. No approval requirement can be bypassed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── The patch that the LLM is allowed to propose ─────────────────────────────
# Intentionally narrow — only safe, structured fields. No system_persona
# override, no raw SQL, no credentials, no external API endpoints.

class ConfigChangePatch(BaseModel):
    """
    The structured diff the LLM may propose.
    Every field is optional — the LLM only fills what changed.

    EXCLUDED (cannot be changed via NL config):
    - system_persona   (requires admin via structured form)
    - llm_model        (requires admin via structured form)
    - autonomy_level   (requires admin via structured form)
    - tenant_id        (immutable)
    - tool governance  (requires explicit structured form — NL may only
                        suggest, not directly change tool scope)
    """
    responsibilities_add: list[str] = Field(
        default_factory=list,
        description="New responsibilities to append to the existing list.",
    )
    responsibilities_remove: list[str] = Field(
        default_factory=list,
        description="Responsibility text to remove (substring match).",
    )
    objectives_add: list[str] = Field(
        default_factory=list,
        description="New objectives to append.",
    )
    objectives_remove: list[str] = Field(
        default_factory=list,
        description="Objective text to remove (substring match).",
    )
    instructions_append: str = Field(
        default="",
        description="Text to append to the instructions field.",
    )
    schedule_add: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Schedule preferences to add. Each must have task (str) and frequency (str).",
    )
    schedule_remove: list[str] = Field(
        default_factory=list,
        description="Schedule task names to remove (exact match).",
    )
    monitoring_rules_add: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Monitoring rules to add. Each must have id, name, condition, action.",
    )
    monitoring_rules_remove: list[str] = Field(
        default_factory=list,
        description="Monitoring rule IDs to remove.",
    )
    quick_prompts_add: list[str] = Field(
        default_factory=list,
        description="Quick prompts to add.",
    )
    quick_prompts_remove: list[str] = Field(
        default_factory=list,
        description="Quick prompts to remove (exact match).",
    )
    communication_style: str | None = Field(
        default=None,
        description="New communication style. Must be one of: Concise, Formal, Consultative.",
    )


# ── Human-readable diff entry ─────────────────────────────────────────────────

class ProposedChangeLine(BaseModel):
    """One line in the human-readable summary shown to the administrator."""
    section: str        # e.g. "Responsibilities", "Schedule", "Monitoring"
    action: Literal["add", "remove", "update"]
    description: str    # e.g. "+ Monitor conversion rates"


# ── Full proposal record ──────────────────────────────────────────────────────

class ConfigProposalOut(BaseModel):
    """
    Returned from POST /api/v1/roles/{role_key}/nl-configure.
    Shown to the administrator before any change is persisted.
    """
    id: str
    role_key: str
    tenant_id: str
    original_instruction: str
    interpreted_intent: str         # short summary of what the LLM understood
    proposed_changes: list[ProposedChangeLine]
    patch: ConfigChangePatch        # structured diff — what will be applied on approval
    validation_errors: list[str]    # empty if safe to approve
    validation_warnings: list[str]
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None


class NLConfigRequest(BaseModel):
    """Request body for POST /api/v1/roles/{role_key}/nl-configure."""
    instruction: str = Field(..., min_length=1, max_length=2000,
        description="The administrator's natural-language configuration instruction.")
    requested_by: str = Field(default="admin",
        description="Identifier of the person making the request.")


class ProposalDecision(BaseModel):
    """Body for POST /api/v1/roles/{role_key}/proposals/{proposal_id}/approve|reject."""
    reviewed_by: str = Field(default="admin")
    review_note: str | None = None
