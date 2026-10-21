"""
EAAWP Dynamic Integration Framework — HTTP Boundary Schemas

These are the Pydantic models for the /api/v1/integration-manager router.

Security rules enforced here
─────────────────────────────
1. encrypted_credentials is NEVER included in any Out schema.
2. Credentials are accepted in Create/Update bodies but never echoed back.
3. has_credentials (bool) indicates whether credentials are stored — never
   the actual value.
4. account_info (safe metadata dict) is the only provider-identity data
   returned after a connection test.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Status ────────────────────────────────────────────────────────────────────

IntegrationStatus = Literal[
    "not_configured", "not_tested", "connected", "failed", "disabled"
]

# ── Provider catalogue ────────────────────────────────────────────────────────


class ProviderCapabilityOut(BaseModel):
    """Safe capability descriptor returned in the provider catalogue."""
    key: str
    display_name: str
    description: str
    category: str
    risk_level: str
    requires_schema_entity: bool


class ProviderCatalogueItem(BaseModel):
    """
    Metadata about one registered provider type.
    Returned by GET /api/v1/integration-manager/providers.
    Never contains credentials or sensitive configuration.
    """
    provider_type: str
    display_name: str
    description: str
    icon_hint: str
    required_credential_fields: list[str]
    optional_credential_fields: list[str]
    capabilities: list[ProviderCapabilityOut]


# ── Integration CRUD ──────────────────────────────────────────────────────────


class IntegrationOut(BaseModel):
    """
    Integration record returned to the frontend.
    encrypted_credentials is excluded — never serialised.
    has_credentials indicates whether credentials are present.
    """
    id: str
    tenant_id: str
    provider_type: str
    display_name: str
    status: IntegrationStatus
    is_enabled: bool
    has_credentials: bool           # True if encrypted_credentials is non-empty
    account_info: dict[str, Any]    # safe metadata from last successful test
    last_tested_at: datetime | None
    error_message: str | None
    legacy_connection_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntegrationCreate(BaseModel):
    """
    Create a new Integration.

    credentials: provider-specific dict accepted here once, encrypted and stored.
                 Example: {"host": "db.example.com", "port": 5432, ...}
                 Never echoed back in any response.
    """
    provider_type: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=255)
    credentials: dict[str, Any] = Field(
        ...,
        description="Provider credentials. Encrypted at rest. Never returned.",
    )
    created_by: str = Field(default="admin", max_length=128)

    @field_validator("provider_type")
    @classmethod
    def provider_type_lowercase(cls, v: str) -> str:
        return v.lower().strip()


class IntegrationUpdate(BaseModel):
    """Partial update — all fields optional."""
    display_name: str | None = Field(default=None, max_length=255)
    credentials: dict[str, Any] | None = Field(
        default=None,
        description="Supply to rotate credentials. Encrypted at rest.",
    )
    is_enabled: bool | None = None


# ── Connection test ───────────────────────────────────────────────────────────


class IntegrationTestResponse(BaseModel):
    """Result of POST /api/v1/integration-manager/integrations/{id}/test"""
    integration_id: str
    provider_type: str
    success: bool
    status: IntegrationStatus
    account_info: dict[str, Any]     # safe provider metadata
    error_message: str | None
    tested_at: datetime


# ── Entity discovery ──────────────────────────────────────────────────────────


class DiscoveredEntityOut(BaseModel):
    """
    One entity (table/view/dataset/endpoint) discovered by an integration.
    Safe metadata only — no credentials, no data rows.
    """
    schema_name: str
    entity_name: str
    entity_type: str           # "table" | "view" | "dataset" | "endpoint"
    column_count: int
    row_count_estimate: int | None
    columns: list[dict[str, Any]]  # [{name, data_type, is_nullable, is_primary_key}]
    description: str = ""          # MCP tools: what the server says the tool does (untrusted text, shown as plain text)
    risk_level: str | None = None  # MCP tools: low | medium | high, classified by EAAWP from the tool name


class DiscoverEntitiesResponse(BaseModel):
    """Result of POST /api/v1/integration-manager/integrations/{id}/discover"""
    integration_id: str
    provider_type: str
    entity_count: int
    entities: list[DiscoveredEntityOut]


# ── Capability grants ─────────────────────────────────────────────────────────


class CapabilityGrantOut(BaseModel):
    """One capability grant record."""
    id: str
    tenant_id: str
    integration_id: str
    role_key: str
    capability_key: str
    is_granted: bool
    granted_by: str
    granted_at: datetime

    model_config = {"from_attributes": True}


class CapabilityGrantCreate(BaseModel):
    """Create a capability grant."""
    role_key: str = Field(..., min_length=1, max_length=128)
    capability_key: str = Field(..., min_length=1, max_length=128)
    is_granted: bool = True
    granted_by: str = Field(default="admin", max_length=128)


class CapabilityGrantBulkCreate(BaseModel):
    """Grant multiple capabilities to multiple roles at once."""
    grants: list[CapabilityGrantCreate]

    @field_validator("grants")
    @classmethod
    def validate_non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("grants list must not be empty")
        if len(v) > 50:
            raise ValueError("maximum 50 grants per bulk operation")
        return v


class CapabilityGrantUpdate(BaseModel):
    """Toggle a grant."""
    is_granted: bool


# ── Execute capability ────────────────────────────────────────────────────────


class ExecuteCapabilityRequest(BaseModel):
    """Request body for POST /api/v1/integration-manager/integrations/{id}/execute"""
    capability_key: str = Field(..., min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    role_key: str = Field(..., min_length=1, max_length=128)


class ExecuteCapabilityResponse(BaseModel):
    """
    Result of executing a capability.
    Never contains credentials or raw connection details.
    """
    integration_id: str
    capability_key: str
    success: bool
    data: list[dict[str, Any]] | dict[str, Any] | str
    row_count: int
    truncated: bool
    source_label: str
    error: str | None


# ── Framework health ──────────────────────────────────────────────────────────


class IntegrationFrameworkStatus(BaseModel):
    """
    Safe summary of the Integration Framework.
    Returned by GET /api/v1/integration-manager/status.
    """
    registered_provider_count: int
    registered_provider_types: list[str]
    is_ready: bool


# ── Dynamic tool discovery ────────────────────────────────────────────────────


class DynamicToolInfo(BaseModel):
    """
    Safe metadata about one dynamic tool available to a role.
    Never contains credentials, connection strings, or sensitive identifiers
    beyond the opaque integration_id UUID.
    Returned by GET /api/v1/integration-manager/tools.
    """
    tool_key: str
    integration_id: str
    integration_name: str
    provider_type: str
    capability_key: str
    description: str
    risk_level: str
    is_read_only: bool
    is_enabled: bool
    input_schema: dict[str, Any] | None


# ── OAuth 2.0 (Phase 4 — Google Search Console) ──────────────────────────────


class OAuthAuthorizeResponse(BaseModel):
    """
    Returned by GET /api/v1/oauth/google/authorize.
    Contains the authorization_url to which the browser must be redirected.
    The state_token is an opaque CSRF token — the frontend should not
    interpret or store it; it is embedded in authorization_url automatically.
    """
    integration_id: str
    authorization_url: str
    state_token: str
    expires_at: str  # ISO-8601 UTC timestamp


class OAuthCallbackResponse(BaseModel):
    """
    OpenAPI documentation schema for the OAuth2 callback redirect query params.
    The endpoint returns a 302 redirect; the frontend reads these params on landing.
    """
    success: str | None = Field(None, description='"true" if authorization succeeded')
    integration_id: str | None = None
    provider_type: str | None = None
    error: str | None = None
    error_description: str | None = None
