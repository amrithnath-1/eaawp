"""
Pydantic v2 schemas for EAAWP Blueprint Parser & Agent Engine.

AgentBlueprint  — the parsed, validated representation of an agent definition.
AgentExecutionRequest  — incoming POST body for /api/v1/agent/execute.
AgentExecutionResponse — outgoing response from the agent engine.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class AgentBlueprint(BaseModel):
    """
    Strongly-typed representation of an EAAWP agent blueprint.
    Parsed from JSON at the API boundary; all downstream engine
    components receive this validated object, never raw dicts.
    """

    agent_id: str = Field(..., min_length=1, description="Unique agent identifier")
    role_name: str = Field(..., min_length=1, description="Human-readable role label")
    system_persona: str = Field(
        ..., min_length=1, description="System prompt injected as the LLM system message"
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tool keys permitted for this agent. Must exist in MASTER_TOOL_REGISTRY.",
    )
    guarded_tools: list[str] = Field(
        default_factory=list,
        description="Tool keys that require human approval before execution.",
    )
    tenant_id: str = Field(..., min_length=1, description="Tenant / organisation identifier")

    @field_validator("allowed_tools", "guarded_tools", mode="before")
    @classmethod
    def must_be_list(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")
        return v


class AgentExecutionRequest(BaseModel):
    """Request body for POST /api/v1/agent/execute."""

    blueprint: AgentBlueprint
    user_prompt: str = Field(..., min_length=1, description="The user's input prompt")
    session_id: str | None = Field(
        default=None, description="Optional session ID for conversation continuity"
    )


class ToolCallDetail(BaseModel):
    """Details of a single tool call requested by the LLM."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionResponse(BaseModel):
    """Response from POST /api/v1/agent/execute."""

    message: str = Field(description="Text content of the LLM response")
    tool_calls: list[ToolCallDetail] = Field(
        default_factory=list, description="Tool calls requested by the LLM, if any"
    )
    sources: list[str] = Field(
        default_factory=list, description="Knowledge sources cited by the agent"
    )
    requires_approval: bool = Field(
        default=False,
        description="True when the agent's proposed action requires human approval",
    )
    session_id: str = Field(description="Session ID for conversation continuity")
