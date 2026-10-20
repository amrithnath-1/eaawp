"""
EAAWP Monitoring Rules Router

Manages monitoring rules for the Autonomous Monitoring and Trigger Engine.

Endpoints
---------
GET    /api/v1/monitoring/rules                — list rules for tenant+role
POST   /api/v1/monitoring/rules                — create a new rule
GET    /api/v1/monitoring/rules/{rule_id}      — get a specific rule
PATCH  /api/v1/monitoring/rules/{rule_id}      — update a rule
DELETE /api/v1/monitoring/rules/{rule_id}      — delete a rule
POST   /api/v1/monitoring/rules/{rule_id}/enable   — enable a rule
POST   /api/v1/monitoring/rules/{rule_id}/disable  — disable a rule
GET    /api/v1/monitoring/rules/{rule_id}/audit    — get audit log for a rule
POST   /api/v1/monitoring/evaluate/{rule_id}   — manually trigger evaluation (admin)
GET    /api/v1/monitoring/status               — scheduler status

All endpoints require X-Tenant-ID header.
Monitoring rules are scoped to DIGITAL_MARKETING_MANAGER (the only
implemented role). Rules for other roles are rejected with 404.

Security model
--------------
- Rules belong to a specific (tenant_id, role_key) pair.
- Conditions are validated at creation time — no arbitrary SQL/code accepted.
- Semantic concepts are validated against the SemanticMapping table.
- All mutations are scoped to the requesting tenant — tenant isolation enforced.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.monitoring_models import MonitoringAuditLog, MonitoringRule
from app.db.models import SemanticMapping
from app.db.session import get_db
from app.schemas.monitoring import (
    ALLOWED_FREQUENCIES,
    MonitoringAuditOut,
    MonitoringRuleCreate,
    MonitoringRuleOut,
    MonitoringRuleUpdate,
)
from app.schemas.role_config import IMPLEMENTED_ROLES
from app.services.monitoring_scheduler import compute_next_evaluation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

# ── Dependency helpers ────────────────────────────────────────────────────────


# ── ORM → schema ──────────────────────────────────────────────────────────────

def _rule_to_out(rule: MonitoringRule) -> MonitoringRuleOut:
    import app.schemas.monitoring as mon_schema
    condition = mon_schema.MonitoringCondition(
        **json.loads(rule.condition_json or "{}")
    )
    return MonitoringRuleOut(
        id=rule.id,
        tenant_id=rule.tenant_id,
        role_key=rule.role_key,
        name=rule.name,
        description=rule.description,
        enabled=rule.enabled,
        semantic_concept=rule.semantic_concept,
        condition=condition,
        evaluation_frequency=rule.evaluation_frequency,
        action_objective=rule.action_objective,
        require_approval_on_trigger=rule.require_approval_on_trigger,
        cooldown_hours=rule.cooldown_hours,
        last_evaluated_at=rule.last_evaluated_at,
        last_triggered_at=rule.last_triggered_at,
        next_evaluation_at=rule.next_evaluation_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        status=rule.status,
        last_evaluation_result=rule.last_evaluation_result,
        last_error_message=rule.last_error_message,
        last_triggered_plan_id=rule.last_triggered_plan_id,
    )


def _audit_to_out(row: MonitoringAuditLog) -> MonitoringAuditOut:
    return MonitoringAuditOut(
        id=row.id,
        tenant_id=row.tenant_id,
        role_key=row.role_key,
        rule_id=row.rule_id,
        rule_name=row.rule_name,
        evaluated_at=row.evaluated_at,
        semantic_concept=row.semantic_concept,
        result=row.result,
        triggered=row.triggered,
        triggered_plan_id=row.triggered_plan_id,
        failure_reason=row.failure_reason,
        current_value=row.current_value,
        previous_value=row.previous_value,
    )


# ── Validation helpers ────────────────────────────────────────────────────────

async def _validate_semantic_concept(
    semantic_concept: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """
    Verify that the semantic concept has at least one mapping for this tenant.
    Raises HTTPException 422 if not found.
    """
    result = await db.execute(
        select(SemanticMapping).where(
            SemanticMapping.tenant_id == tenant_id,
            SemanticMapping.semantic_concept == semantic_concept,
        ).limit(1)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No semantic mapping found for concept '{semantic_concept}' "
                f"in this tenant. Create a mapping via the Semantic Data Mapping "
                f"panel before creating a monitoring rule."
            ),
        )


def _require_implemented_role(role_key: str) -> None:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "Monitoring rules are only available for implemented roles.",
            },
        )


# ── List rules ────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=list[MonitoringRuleOut])
async def list_monitoring_rules(
    role_key: str = "DIGITAL_MARKETING_MANAGER",
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[MonitoringRuleOut]:
    """List all monitoring rules for the tenant and role."""
    _require_implemented_role(role_key)

    result = await db.execute(
        select(MonitoringRule)
        .where(
            MonitoringRule.tenant_id == tenant_id,
            MonitoringRule.role_key == role_key,
        )
        .order_by(MonitoringRule.created_at.desc())
    )
    rules = result.scalars().all()
    return [_rule_to_out(r) for r in rules]


# ── Create rule ───────────────────────────────────────────────────────────────

@router.post("/rules", response_model=MonitoringRuleOut, status_code=201)
async def create_monitoring_rule(
    body: MonitoringRuleCreate,
    role_key: str = "DIGITAL_MARKETING_MANAGER",
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MonitoringRuleOut:
    """
    Create a new monitoring rule.
    The semantic concept must have an existing mapping for this tenant.
    The condition must be structured — no arbitrary SQL or code.
    """
    _require_implemented_role(role_key)

    # Validate semantic concept has a mapping
    await _validate_semantic_concept(body.semantic_concept, tenant_id, db)

    now = datetime.now(timezone.utc)
    next_eval = compute_next_evaluation(body.evaluation_frequency, now)

    rule = MonitoringRule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role_key=role_key,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        semantic_concept=body.semantic_concept,
        condition_json=json.dumps(body.condition.model_dump()),
        evaluation_frequency=body.evaluation_frequency,
        action_objective=body.action_objective,
        require_approval_on_trigger=body.require_approval_on_trigger,
        cooldown_hours=body.cooldown_hours,
        next_evaluation_at=next_eval if body.enabled else None,
        status="idle" if body.enabled else "disabled",
    )
    db.add(rule)
    await db.flush()

    logger.info(
        "Monitoring rule created: %s (tenant=%s, role=%s, concept=%s)",
        rule.id, tenant_id, role_key, body.semantic_concept,
    )
    return _rule_to_out(rule)


# ── Get rule ──────────────────────────────────────────────────────────────────

@router.get("/rules/{rule_id}", response_model=MonitoringRuleOut)
async def get_monitoring_rule(
    rule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MonitoringRuleOut:
    rule = await _load_rule(rule_id, tenant_id, db)
    return _rule_to_out(rule)


# ── Update rule ───────────────────────────────────────────────────────────────

@router.patch("/rules/{rule_id}", response_model=MonitoringRuleOut)
async def update_monitoring_rule(
    rule_id: str,
    body: MonitoringRuleUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MonitoringRuleOut:
    """Partially update a monitoring rule."""
    rule = await _load_rule(rule_id, tenant_id, db)

    if body.name is not None:
        rule.name = body.name
    if body.description is not None:
        rule.description = body.description
    if body.enabled is not None:
        rule.enabled = body.enabled
        if body.enabled:
            rule.status = "idle"
            if rule.next_evaluation_at is None:
                rule.next_evaluation_at = compute_next_evaluation(
                    rule.evaluation_frequency, datetime.now(timezone.utc)
                )
        else:
            rule.status = "disabled"
    if body.semantic_concept is not None:
        await _validate_semantic_concept(body.semantic_concept, tenant_id, db)
        rule.semantic_concept = body.semantic_concept
    if body.condition is not None:
        rule.condition_json = json.dumps(body.condition.model_dump())
    if body.evaluation_frequency is not None:
        rule.evaluation_frequency = body.evaluation_frequency
        # Recompute next evaluation with new frequency
        rule.next_evaluation_at = compute_next_evaluation(
            body.evaluation_frequency, datetime.now(timezone.utc)
        )
    if body.action_objective is not None:
        rule.action_objective = body.action_objective
    if body.require_approval_on_trigger is not None:
        rule.require_approval_on_trigger = body.require_approval_on_trigger
    if body.cooldown_hours is not None:
        rule.cooldown_hours = body.cooldown_hours

    await db.flush()
    return _rule_to_out(rule)


# ── Delete rule ───────────────────────────────────────────────────────────────

@router.delete("/rules/{rule_id}", status_code=204, response_model=None)
async def delete_monitoring_rule(
    rule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await _load_rule(rule_id, tenant_id, db)
    await db.delete(rule)
    await db.flush()
    logger.info("Monitoring rule deleted: %s (tenant=%s)", rule_id, tenant_id)


# ── Enable / disable ──────────────────────────────────────────────────────────

@router.post("/rules/{rule_id}/enable", response_model=MonitoringRuleOut)
async def enable_monitoring_rule(
    rule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MonitoringRuleOut:
    rule = await _load_rule(rule_id, tenant_id, db)
    rule.enabled = True
    rule.status = "idle"
    rule.next_evaluation_at = compute_next_evaluation(
        rule.evaluation_frequency, datetime.now(timezone.utc)
    )
    await db.flush()
    return _rule_to_out(rule)


@router.post("/rules/{rule_id}/disable", response_model=MonitoringRuleOut)
async def disable_monitoring_rule(
    rule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MonitoringRuleOut:
    rule = await _load_rule(rule_id, tenant_id, db)
    rule.enabled = False
    rule.status = "disabled"
    await db.flush()
    return _rule_to_out(rule)


# ── Audit log for a rule ──────────────────────────────────────────────────────

@router.get("/rules/{rule_id}/audit", response_model=list[MonitoringAuditOut])
async def get_rule_audit(
    rule_id: str,
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[MonitoringAuditOut]:
    """Get the evaluation audit log for a specific monitoring rule."""
    # Verify rule belongs to tenant
    await _load_rule(rule_id, tenant_id, db)

    result = await db.execute(
        select(MonitoringAuditLog)
        .where(
            MonitoringAuditLog.rule_id == rule_id,
            MonitoringAuditLog.tenant_id == tenant_id,
        )
        .order_by(MonitoringAuditLog.evaluated_at.desc())
        .limit(min(limit, 200))
    )
    rows = result.scalars().all()
    return [_audit_to_out(r) for r in rows]


# ── Manual evaluation trigger (admin only) ────────────────────────────────────

@router.post("/evaluate/{rule_id}", response_model=dict)
async def manually_evaluate_rule(
    rule_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Manually trigger an evaluation of a monitoring rule.
    Useful for testing or administrative override.
    The rule does not need to be enabled for manual evaluation,
    but it must exist and belong to this tenant.
    """
    # Verify ownership
    await _load_rule(rule_id, tenant_id, db)

    from app.services.monitoring_engine import evaluate_rule
    result = await evaluate_rule(rule_id, tenant_id, db)
    return result


# ── Scheduler status ──────────────────────────────────────────────────────────

@router.get("/status", response_model=dict)
async def monitoring_status(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return monitoring scheduler status and rule counts for this tenant."""
    from app.services.monitoring_scheduler import is_running

    total_result = await db.execute(
        select(MonitoringRule).where(MonitoringRule.tenant_id == tenant_id)
    )
    all_rules = total_result.scalars().all()

    enabled = sum(1 for r in all_rules if r.enabled)
    triggered = sum(1 for r in all_rules if r.last_triggered_at is not None)
    errors = sum(1 for r in all_rules if r.status == "error")

    return {
        "scheduler_running": is_running(),
        "total_rules": len(all_rules),
        "enabled_rules": enabled,
        "triggered_rules": triggered,
        "error_rules": errors,
        "note": (
            "Real monitoring is active. Rules evaluate on their configured frequency "
            "and create plans via the existing planning engine when conditions are met."
            if is_running()
            else "Scheduler is not running — this is mock/test mode."
        ),
    }


# ── Private helpers ───────────────────────────────────────────────────────────

async def _load_rule(
    rule_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> MonitoringRule:
    """Load a monitoring rule, enforcing tenant isolation."""
    result = await db.execute(
        select(MonitoringRule).where(
            MonitoringRule.id == rule_id,
            MonitoringRule.tenant_id == tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Monitoring rule not found.")
    return rule
