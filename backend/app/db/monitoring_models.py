"""
EAAWP Monitoring ORM Models

Separate file to keep monitoring models isolated from the main models.py
so they can be imported selectively and to avoid circular imports.

Security invariants
-------------------
- MonitoringRule.condition_json stores only structured, validated condition data.
- MonitoringAuditLog stores only safe metadata — no credentials, raw SQL, or
  row-level company data. Only the computed aggregate value is stored.
- Tenant isolation: every row carries tenant_id; all queries MUST filter by it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class MonitoringRule(Base):
    """
    A persistent monitoring rule belonging to a tenant + role_key pair.

    The rule is evaluated by the scheduler on the configured frequency.
    When the condition is true, an ExecutionPlan is created via the existing
    planning engine — this model never directly executes actions.

    Status values:
        idle        — enabled but not currently being evaluated
        evaluating  — a scheduler lock is held; evaluation in progress
        triggered   — last evaluation triggered a plan
        error       — last evaluation produced an error
        disabled    — rule is disabled; scheduler skips it
    """

    __tablename__ = "monitoring_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Data scope
    semantic_concept: Mapped[str] = mapped_column(String(128), nullable=False)

    # Structured condition — JSON-serialised MonitoringCondition
    # NEVER contains SQL expressions, Python code, or arbitrary HTTP requests.
    condition_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Scheduling
    evaluation_frequency: Mapped[str] = mapped_column(
        String(32), nullable=False, default="daily"
    )

    # What to do when triggered
    action_objective: Mapped[str] = mapped_column(Text, nullable=False)
    require_approval_on_trigger: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Deduplication / cooldown
    cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_evaluation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Operational state
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="idle"
    )
    last_evaluation_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_triggered_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Scheduler concurrency lock — prevents duplicate concurrent evaluations.
    # This is a simple advisory flag; the scheduler checks+sets atomically.
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonitoringAuditLog(Base):
    """
    Safe audit record for a single monitoring rule evaluation.

    Security: never stores credentials, raw SQL, row-level company data, or
    chain-of-thought. Only the computed aggregate value and safe error text.
    """

    __tablename__ = "monitoring_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("monitoring_rules.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    semantic_concept: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # Evaluation outcome
    result: Mapped[str] = mapped_column(
        String(32), nullable=False, default="condition_false"
    )  # condition_false | condition_true | error | permission_denied | no_data
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Safe error message — never credentials/SQL
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Only aggregate values — never raw data rows
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
