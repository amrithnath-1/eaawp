"""
EAAWP Phase B — Natural Language Integration Manager Schemas

These schemas represent the structured output of parsing a natural-language
request about integrations. The LLM proposes; the backend validates and decides.

Security invariants:
- The LLM produces IntegrationIntent — a structured proposal.
- The backend validates every field before acting.
- The LLM cannot directly set credentials, tenant_id, or risk overrides.
- IntegrationConversationState is server-side; never trust a client-supplied state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Intent types ──────────────────────────────────────────────────────────────

IntentType = Literal[
    "CONNECT_INTEGRATION",
    "DISCONNECT_INTEGRATION",
    "LIST_INTEGRATIONS",
    "LIST_CAPABILITIES",
    "GRANT_CAPABILITY",
    "REVOKE_CAPABILITY",
    "CHECK_STATUS",
    "TEST_CONNECTION",
    "UNKNOWN",
]

# Registered provider types the NL layer is allowed to reference.
KNOWN_PROVIDERS = frozenset([
    "google_search_console",
    "google_analytics",
    "facebook",
    "github",
    "postgresql",
    "mysql",
    "mcp",
])


class IntegrationIntent(BaseModel):
    """
    Structured representation of what the user wants to do with an integration.
    Produced by the LLM from a natural-language input.
    The backend validates every field before taking any action.
    """
    intent_type: IntentType = Field(..., description="The classified intent")
    provider_type: str | None = Field(
        None,
        description="Canonical provider type string, e.g. 'google_search_console'",
        max_length=64,
    )
    requested_capabilities: list[str] = Field(
        default_factory=list,
        description="Capability keys the user wants to use",
        max_length=20,
    )
    target_role_key: str | None = Field(
        None,
        description="Role that should receive capability grants, e.g. 'DIGITAL_MARKETING_MANAGER'",
        max_length=128,
    )
    display_name: str | None = Field(
        None,
        description="Human-friendly name for the integration",
        max_length=255,
    )
    reasoning: str = Field(
        default="",
        description="LLM reasoning for this classification",
        max_length=500,
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score 0–1",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Information the system needs before proceeding",
        max_length=10,
    )

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str | None) -> str | None:
        """Reject provider_type values not in the known set."""
        if v is not None and v.lower() not in KNOWN_PROVIDERS:
            # Unknown provider — return None so the response asks the user to clarify
            return None
        return v.lower() if v else None


class IntegrationConversationTurn(BaseModel):
    """One turn in an integration setup conversation."""
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)
    intent: IntegrationIntent | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IntegrationConversationRequest(BaseModel):
    """Request to continue an integration setup conversation."""
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = Field(None, description="Existing conversation ID to continue")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional context: integration_id, current_step, etc.",
    )


class IntegrationConversationResponse(BaseModel):
    """Response from the NL integration setup conversation."""
    conversation_id: str
    reply: str = Field(..., description="Natural-language assistant reply")
    intent: IntegrationIntent | None = Field(None, description="Parsed intent if detected")
    next_action: Literal[
        "NONE",
        "REDIRECT_TO_OAUTH",
        "SHOW_CAPABILITIES",
        "REQUEST_CREDENTIALS",
        "CONFIRM_GRANT",
        "SHOW_STATUS",
        "CLARIFY",
        "OPEN_GITHUB_FORM",
        "OPEN_MCP_FORM",
        "UNAVAILABLE",
    ] = "NONE"
    action_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Data needed for the next_action (e.g. authorization_url)",
    )
    available_providers: list[dict[str, str]] = Field(
        default_factory=list,
        description="Providers relevant to the conversation",
    )


class NLIntegrationRequest(BaseModel):
    """Simple one-shot NL integration request."""
    instruction: str = Field(..., min_length=1, max_length=2000)
    requested_by: str = Field(default="admin", max_length=128)
