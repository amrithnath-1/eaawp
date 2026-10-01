"""
EAAWP Dynamic Integration Framework — ORM Models

Two new tables:

integration_catalog
───────────────────
A generic, provider-agnostic record of an external system connection.
One row per tenant per provider instance (a tenant may have multiple rows
of the same provider_type with different credentials, e.g. two PostgreSQL
databases).

This is the generic counterpart to DataConnection (PostgreSQL/MySQL),
ExternalIntegration (SMTP), and MarketingChannelIntegration (channels).
Those existing tables are NOT replaced — the integration_catalog holds
the unified view and cross-references back where appropriate.

capability_grants
─────────────────
Controls which AI employees (role_keys) are permitted to invoke which
capabilities of which integration.

One row = one (integration_id, role_key, capability_key) triple.
is_granted=False is stored explicitly to support denials (future use).

The AI agent execution layer checks capability_grants before invoking
any integration capability.

Credential handling
───────────────────
- encrypted_credentials: Text — a JSON blob (dict[str, str]) encrypted with
  Fernet (same as existing crypto.py).  Individual fields are NOT stored as
  separate columns because different providers have different credential shapes.
- The plain-text credentials dict is NEVER persisted, logged, or returned
  in API responses.
- Only `has_credentials` (bool) is safe to expose externally.

Status lifecycle
────────────────
not_configured → not_tested → connected
                             → failed
Any state → disabled
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.models import Base  # reuse the existing declarative base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Integration Catalog ───────────────────────────────────────────────────────

class Integration(Base):
    """
    A generic, provider-agnostic record of one external system connection
    belonging to one tenant.

    This is the central record for the Integration Framework.
    All other integration-adjacent data (entities, grants) references this.

    Fields that must NEVER be returned in API responses:
        encrypted_credentials — contains encrypted secrets
    """

    __tablename__ = "integration_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # ── Provider identity ─────────────────────────────────────────────────────
    provider_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        # e.g. "postgresql", "mysql", "google_analytics", "github", "smtp"
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Credentials — encrypted at rest, NEVER returned to frontend ───────────
    # JSON blob {field_name: value} encrypted with Fernet (app.integrations.crypto).
    # Empty string means no credentials stored yet.
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Status / health ───────────────────────────────────────────────────────
    # not_configured | not_tested | connected | failed | disabled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_configured")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Sanitised error — no credentials, max 500 chars
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Safe metadata returned from test_connection / discover_entities ───────
    # JSON object with provider-specific safe metadata (account name, version, etc.)
    # e.g. {"server_version": "PostgreSQL 15.2", "account": "my-org"}
    account_info_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # ── Optional cross-reference to the legacy DB-connection tables ───────────
    # Populated when this Integration wraps an existing DataConnection row.
    # Null for non-DB providers.
    legacy_connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Audit fields ──────────────────────────────────────────────────────────
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # One tenant may have multiple integrations of the same provider type
    # (e.g. two PostgreSQL databases) — no unique constraint on (tenant_id, provider_type)


# ── Capability Grants ─────────────────────────────────────────────────────────

class CapabilityGrant(Base):
    """
    Controls which AI employee roles are permitted to invoke a specific
    capability of a specific Integration.

    Enforcement
    ───────────
    Before the Integration Manager executes a capability on behalf of an
    agent, it checks:
        SELECT * FROM capability_grants
        WHERE integration_id = ? AND role_key = ? AND capability_key = ?
              AND is_granted = TRUE

    If no matching granted row is found, the execution is denied with a
    PermissionError.

    Granularity
    ───────────
    Permission is per (integration, role, capability) triple.
    This allows, for example:
        - DMM can run "query_entity" on the analytics DB
        - DMM cannot run "discover_schema" on the analytics DB
        - Financial Analyst can run "discover_schema" but not "query_entity"

    Granted-by audit
    ────────────────
    `granted_by` stores who granted the permission (admin user or system).
    `granted_at` stores when it was granted.
    """

    __tablename__ = "capability_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integration_catalog.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # The role key of the AI employee receiving this grant
    # e.g. "DIGITAL_MARKETING_MANAGER", "FINANCIAL_ANALYST"
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # The capability key within the provider
    # e.g. "query_entity", "discover_schema", "get_analytics"
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # True = permission granted.  False = explicitly denied (reserved for future use).
    is_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    granted_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "integration_id", "role_key", "capability_key",
            name="uq_capability_grant_integration_role_cap",
        ),
    )


# ── Dynamic Tool Audit Log ────────────────────────────────────────────────────

class DynamicToolAuditLog(Base):
    """
    Audit record for every dynamic integration tool execution.

    Written by the Phase 3 adapter after each capability execution.
    Contains safe metadata only — NO credentials, NO connection strings,
    NO raw SQL, NO sensitive row data.

    One row per tool invocation.  Used for:
    - Security monitoring (unusual access patterns)
    - Debugging (which tool was called, what happened)
    - Compliance (who accessed what data, when)
    - Governance evidence for approval workflows
    """

    __tablename__ = "dynamic_tool_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    integration_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        # No FK cascade — audit records should survive integration deletion
    )
    # The role/AI employee that invoked the tool
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # The provider capability that was executed (e.g. "query_entity")
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # The deterministic tool key (e.g. "integration_a1b2c3d4_query_entity")
    tool_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Execution outcome
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Sanitised error text — max 500 chars, no credentials
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Timestamp — indexed for time-range queries
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
