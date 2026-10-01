"""add_production_indexes

Revision ID: s6t0u15v7w13
Revises: r5s9t04u6v12
Create Date: 2026-09-24

Adds composite and covering indexes for production-scale tenant-scoped queries.
All existing indexes remain; this migration only adds new ones.
"""

from __future__ import annotations

from alembic import op

revision = "s6t0u15v7w13"
down_revision = "r5s9t04u6v12"
branch_labels = None
depends_on = None


def _idx(name: str, table: str, *cols: str, unique: bool = False) -> None:
    """Create index only if it doesn't already exist (idempotent)."""
    op.create_index(name, table, list(cols), unique=unique, if_not_exists=True)


def upgrade() -> None:
    # ── Tenant + status composite indexes (most common query pattern) ─────────
    _idx("ix_ai_employees_tenant_status", "ai_employees", "tenant_id", "status")
    _idx("ix_tasks_tenant_status", "tasks", "tenant_id", "status")
    _idx("ix_execution_plans_tenant_status", "execution_plans", "tenant_id", "status")
    _idx("ix_approval_requests_tenant_status", "approval_requests", "tenant_id", "status")
    _idx("ix_audit_logs_tenant_created", "audit_logs", "tenant_id", "created_at")
    _idx("ix_activity_events_tenant_created", "activity_events", "tenant_id", "created_at")
    _idx("ix_agent_memories_tenant_role", "agent_memories", "tenant_id", "role_key")
    _idx("ix_agent_memories_tenant_category", "agent_memories", "tenant_id", "category")
    _idx("ix_integration_catalog_tenant_type", "integration_catalog", "tenant_id", "provider_type")
    _idx("ix_capability_grants_tenant_integration", "capability_grants", "tenant_id", "integration_id")
    _idx("ix_capability_grants_tenant_role", "capability_grants", "tenant_id", "role_key")

    # ── New table indexes ─────────────────────────────────────────────────────
    _idx("ix_employee_blueprint_proposals_tenant_status", "employee_blueprint_proposals", "tenant_id", "approval_status")
    _idx("ix_workflows_tenant_enabled", "workflows", "tenant_id", "is_enabled")
    _idx("ix_workflows_tenant_trigger", "workflows", "tenant_id", "trigger")


def downgrade() -> None:
    # Drop only the indexes added in this migration
    indexes = [
        ("ix_ai_employees_tenant_status", "ai_employees"),
        ("ix_tasks_tenant_status", "tasks"),
        ("ix_execution_plans_tenant_status", "execution_plans"),
        ("ix_approval_requests_tenant_status", "approval_requests"),
        ("ix_audit_logs_tenant_created", "audit_logs"),
        ("ix_activity_events_tenant_created", "activity_events"),
        ("ix_agent_memories_tenant_role", "agent_memories"),
        ("ix_agent_memories_tenant_category", "agent_memories"),
        ("ix_integration_catalog_tenant_type", "integration_catalog"),
        ("ix_capability_grants_tenant_integration", "capability_grants"),
        ("ix_capability_grants_tenant_role", "capability_grants"),
        ("ix_employee_blueprint_proposals_tenant_status", "employee_blueprint_proposals"),
        ("ix_workflows_tenant_enabled", "workflows"),
        ("ix_workflows_tenant_trigger", "workflows"),
    ]
    for name, table in indexes:
        op.drop_index(name, table_name=table, if_exists=True)
