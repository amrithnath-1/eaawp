"""
EAAWP Autonomous Monitoring Engine

This is the core execution engine for monitoring rule evaluation.

Architecture
------------
- The engine is NOT a second agent. It calls the existing planning engine
  (create_and_execute_plan) to create plans, and those plans use the existing
  action governance, approval system, and audit trail.
- The engine itself only: reads rules, evaluates conditions, decides whether
  to trigger, and if so, delegates to the planner.

Security invariants
-------------------
1. Every evaluation re-validates: tenant → role → blueprint permissions.
2. Conditions are structured — no SQL injection, no code execution.
3. Data access goes through execute_company_data_query (controlled).
4. The engine NEVER directly executes actions — only creates plans.
5. Duplicate trigger protection via cooldown_hours and is_locked flag.
6. Failures are recorded safely — no credentials in audit logs.
7. Concurrent evaluation of the same rule is prevented by is_locked.

Evaluation flow per rule
------------------------
1. Load rule, verify tenant and role.
2. Verify blueprint permissions (re-load from RoleConfiguration).
3. Verify semantic concept has a mapping (via data_access resolution).
4. Query data through execute_company_data_query.
5. Evaluate structured condition.
6. If condition_false → record evaluation, update timestamps, stop.
7. If condition_true and within cooldown → record evaluation, skip trigger.
8. If condition_true and past cooldown → create AgentPlan via existing planner.
9. Record audit log with rule_id, result, plan_id (if created).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.monitoring_models import MonitoringAuditLog, MonitoringRule
from app.db.models import RoleConfiguration
from app.schemas.blueprint import AgentBlueprint
from app.schemas.monitoring import MonitoringCondition
from app.services.monitoring_evaluator import EvaluationResult, evaluate_condition
from app.services.role_charter import role_system_prompt

logger = logging.getLogger(__name__)

# Staleness threshold for locks: if a rule has been locked for more than
# LOCK_STALE_MINUTES minutes, treat the lock as stale and release it.
LOCK_STALE_MINUTES = 30


# ── Main evaluation entry point ───────────────────────────────────────────────

async def evaluate_rule(
    rule_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Evaluate a single monitoring rule.
    Returns a safe summary dict for logging/response.

    This function is called by the scheduler. It is designed to be safe to
    call concurrently — concurrent calls for the SAME rule are deduped via
    the is_locked flag.
    """
    now = datetime.now(timezone.utc)

    # ── 1. Load rule ──────────────────────────────────────────────────────────
    rule_result = await db.execute(
        select(MonitoringRule).where(
            MonitoringRule.id == rule_id,
            MonitoringRule.tenant_id == tenant_id,
        )
    )
    rule = rule_result.scalar_one_or_none()
    if not rule:
        return {"error": f"Rule {rule_id} not found for tenant {tenant_id}"}

    if not rule.enabled:
        return {"skipped": "Rule is disabled"}

    # ── 2. Check for stale locks (cleanup) ────────────────────────────────────
    if rule.is_locked and rule.locked_at:
        elapsed_minutes = (now - rule.locked_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
        if elapsed_minutes > LOCK_STALE_MINUTES:
            logger.warning(
                "Stale lock detected on monitoring rule %s (tenant %s) — releasing",
                rule_id, tenant_id,
            )
            rule.is_locked = False
            rule.locked_at = None
            await db.flush()

    # ── 3. Prevent concurrent evaluation ─────────────────────────────────────
    if rule.is_locked:
        logger.info(
            "Monitoring rule %s (tenant %s) is already being evaluated — skipping",
            rule_id, tenant_id,
        )
        return {"skipped": "Rule is currently being evaluated by another process"}

    # Acquire lock
    rule.is_locked = True
    rule.locked_at = now
    rule.status = "evaluating"
    await db.flush()

    try:
        return await _do_evaluate(rule, tenant_id, now, db)
    except Exception as exc:
        # Catch-all: never lose the lock permanently on unexpected errors
        logger.error(
            "Unexpected error evaluating rule %s (tenant %s): %s",
            rule_id, tenant_id, exc,
        )
        rule.is_locked = False
        rule.locked_at = None
        rule.status = "error"
        rule.last_evaluated_at = now
        rule.last_evaluation_result = "error"
        rule.last_error_message = str(exc)[:400]
        await _write_audit(db, rule, tenant_id, "error", False, None, None, None, str(exc)[:400])
        await db.flush()
        return {"error": str(exc)[:200]}


async def _do_evaluate(
    rule: MonitoringRule,
    tenant_id: str,
    now: datetime,
    db: AsyncSession,
) -> dict[str, Any]:
    """Core evaluation logic — runs inside the lock."""

    # ── Step 2: Verify tenant and role ────────────────────────────────────────
    role_result = await db.execute(
        select(RoleConfiguration).where(
            RoleConfiguration.tenant_id == tenant_id,
            RoleConfiguration.role_key == rule.role_key,
        )
    )
    role_config = role_result.scalar_one_or_none()

    if not role_config:
        await _fail(rule, tenant_id, now, db,
                    f"No role configuration found for role_key='{rule.role_key}' in this tenant.")
        return {"error": "No role configuration found"}

    # ── Step 3: Build blueprint from current role config ──────────────────────
    tool_scopes_raw: list[dict] = json.loads(role_config.tool_scopes_json or "[]")
    allowed_tools = [
        t["tool_key"] for t in tool_scopes_raw
        if t.get("governance") == "enabled"
    ]
    guarded_tools = [
        t["tool_key"] for t in tool_scopes_raw
        if t.get("governance") == "requires_approval"
    ]

    blueprint = AgentBlueprint(
        agent_id=f"{tenant_id}-{rule.role_key.lower()}",
        role_name=role_config.role_name,
        role_key=rule.role_key,
        system_persona=await role_system_prompt(db, tenant_id, rule.role_key),
        allowed_tools=allowed_tools,
        guarded_tools=guarded_tools,
        tenant_id=tenant_id,
    )

    # ── Step 4: Parse condition ───────────────────────────────────────────────
    try:
        condition = MonitoringCondition(**json.loads(rule.condition_json or "{}"))
    except Exception as exc:
        await _fail(rule, tenant_id, now, db, f"Invalid condition JSON: {exc}")
        return {"error": f"Invalid condition: {exc}"}

    # ── Step 5: Evaluate condition via controlled data access ─────────────────
    eval_result: EvaluationResult = await evaluate_condition(
        condition=condition,
        semantic_concept=rule.semantic_concept,
        tenant_id=tenant_id,
        role_key=rule.role_key,
        db=db,
    )

    # ── Step 6: Handle permission denied / error ──────────────────────────────
    if eval_result.result_code in ("error", "permission_denied"):
        await _fail(
            rule, tenant_id, now, db,
            eval_result.error_message or eval_result.result_code,
            result_code=eval_result.result_code,
            current_value=eval_result.current_value,
        )
        return {"error": eval_result.error_message or eval_result.result_code}

    # ── Step 7: Condition false → record and stop ─────────────────────────────
    if not eval_result.triggered:
        from app.services.monitoring_scheduler import compute_next_evaluation
        next_eval = compute_next_evaluation(rule.evaluation_frequency, now)

        rule.is_locked = False
        rule.locked_at = None
        rule.status = "idle"
        rule.last_evaluated_at = now
        rule.next_evaluation_at = next_eval
        rule.last_evaluation_result = eval_result.result_code
        rule.last_error_message = None

        await _write_audit(
            db, rule, tenant_id,
            eval_result.result_code, False, None,
            eval_result.current_value, eval_result.previous_value, None,
        )
        await db.flush()
        return {"triggered": False, "result": eval_result.result_code}

    # ── Step 8: Condition true — check cooldown ───────────────────────────────
    if rule.last_triggered_at is not None:
        last_triggered = rule.last_triggered_at
        if last_triggered.tzinfo is None:
            last_triggered = last_triggered.replace(tzinfo=timezone.utc)
        elapsed_hours = (now - last_triggered).total_seconds() / 3600.0
        if elapsed_hours < rule.cooldown_hours:
            # Within cooldown — record but do not trigger
            from app.services.monitoring_scheduler import compute_next_evaluation
            next_eval = compute_next_evaluation(rule.evaluation_frequency, now)
            rule.is_locked = False
            rule.locked_at = None
            rule.status = "idle"
            rule.last_evaluated_at = now
            rule.next_evaluation_at = next_eval
            rule.last_evaluation_result = "condition_true_cooldown"

            await _write_audit(
                db, rule, tenant_id,
                "condition_true_cooldown", False, None,
                eval_result.current_value, eval_result.previous_value, None,
            )
            await db.flush()
            logger.info(
                "Monitoring rule %s triggered but within cooldown (%.1fh < %dh required) — skipping plan creation",
                rule.id, elapsed_hours, rule.cooldown_hours,
            )
            return {"triggered": False, "result": "cooldown_active"}

    # ── Step 9: Create plan via existing planning engine ──────────────────────
    plan_id: str | None = None
    plan_error: str | None = None

    try:
        plan_id = await _create_plan_for_rule(rule, blueprint, db, tenant_id)
    except Exception as exc:
        plan_error = str(exc)[:400]
        logger.error(
            "Failed to create plan for monitoring rule %s (tenant %s): %s",
            rule.id, tenant_id, plan_error,
        )

    # ── Step 10: Record trigger ───────────────────────────────────────────────
    from app.services.monitoring_scheduler import compute_next_evaluation
    next_eval = compute_next_evaluation(rule.evaluation_frequency, now)

    rule.is_locked = False
    rule.locked_at = None
    rule.last_evaluated_at = now
    rule.next_evaluation_at = next_eval
    rule.last_evaluation_result = "condition_true"
    rule.last_error_message = plan_error
    rule.last_triggered_plan_id = plan_id

    if plan_error:
        rule.status = "error"
    else:
        rule.status = "triggered"
        rule.last_triggered_at = now

    await _write_audit(
        db, rule, tenant_id,
        "condition_true", True, plan_id,
        eval_result.current_value, eval_result.previous_value,
        plan_error,
    )
    await db.flush()
    from app.services.notification_service import notify_admins
    await notify_admins(db, tenant_id, "monitoring_alert", f"Monitoring rule triggered: {str(getattr(rule, 'name', 'rule'))[:80]}",
                        "A monitoring condition was met." + (" The AI could not prepare a plan." if plan_error else ""),
                        severity="critical" if plan_error else "warning", related_id=rule.id, related_type="monitoring_rule")

    logger.info(
        "Monitoring rule %s triggered for tenant %s — plan_id=%s",
        rule.id, tenant_id, plan_id,
    )

    return {
        "triggered": True,
        "plan_id": plan_id,
        "result": "condition_true",
        "current_value": eval_result.current_value,
        "previous_value": eval_result.previous_value,
    }


async def _create_plan_for_rule(
    rule: MonitoringRule,
    blueprint: AgentBlueprint,
    db: AsyncSession,
    tenant_id: str,
) -> str:
    """
    Create an execution plan for a triggered monitoring rule.
    Uses the EXISTING planning engine — this is NOT a second agent.
    """
    from app.services.planner import create_and_execute_plan

    # Build a user-visible objective from the rule's action_objective
    objective = (
        f"[Monitoring Trigger] {rule.name}: {rule.action_objective}"
    )[:500]

    final_message, plan_id, _ = await create_and_execute_plan(
        user_prompt=objective,
        blueprint=blueprint,
        session_id=f"monitoring-{rule.id}",
        db=db,
        system_persona=blueprint.system_persona,
        data_context_block=f"Monitoring condition triggered: {rule.name}",
        rag_context="",
    )

    return plan_id


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fail(
    rule: MonitoringRule,
    tenant_id: str,
    now: datetime,
    db: AsyncSession,
    error_message: str,
    result_code: str = "error",
    current_value: float | None = None,
) -> None:
    """Record a failed evaluation and release the lock."""
    from app.services.monitoring_scheduler import compute_next_evaluation
    next_eval = compute_next_evaluation(rule.evaluation_frequency, now)

    rule.is_locked = False
    rule.locked_at = None
    rule.status = "error"
    rule.last_evaluated_at = now
    rule.next_evaluation_at = next_eval
    rule.last_evaluation_result = result_code
    rule.last_error_message = error_message[:400]

    await _write_audit(
        db, rule, tenant_id,
        result_code, False, None,
        current_value, None, error_message[:400],
    )
    await db.flush()


async def _write_audit(
    db: AsyncSession,
    rule: MonitoringRule,
    tenant_id: str,
    result_code: str,
    triggered: bool,
    plan_id: str | None,
    current_value: float | None,
    previous_value: float | None,
    failure_reason: str | None,
) -> None:
    """
    Write a safe audit log entry.
    Never stores credentials, raw SQL, or row-level company data.
    """
    try:
        audit = MonitoringAuditLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            role_key=rule.role_key,
            rule_id=rule.id,
            rule_name=rule.name,
            evaluated_at=datetime.now(timezone.utc),
            semantic_concept=rule.semantic_concept,
            result=result_code,
            triggered=triggered,
            triggered_plan_id=plan_id,
            failure_reason=failure_reason,
            current_value=current_value,
            previous_value=previous_value,
        )
        db.add(audit)
    except Exception as exc:
        logger.error("Failed to write monitoring audit log: %s", exc)
