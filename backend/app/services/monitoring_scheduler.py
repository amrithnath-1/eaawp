"""
EAAWP Monitoring & Workflow Scheduler

A lightweight in-process scheduler that runs:
  1. Monitoring rule evaluations on a configurable cadence.
  2. Scheduled Workflow records at their configured cron time.

Design
------
- Uses asyncio background tasks (started via FastAPI lifespan).
- No external dependencies (no Celery, no APScheduler, no Redis).
- Minimum granularity: one minute, matching the smallest supported cron unit.
- Duplicate concurrent execution prevented by is_locked flags.
- Workflows with trigger="scheduled" and schedule_cron are run when due.
- Disabled workflows are never run.
- Each workflow execution runs in its own DB session.

Security
--------
- The scheduler does NOT have elevated permissions.
- It creates a new database session per tick.
- Workflow execution goes through the same planner + governance pipeline
  as a manual trigger — HIGH-risk actions still require approval.
- Credentials and secrets are never accessible from the scheduler context.

Cron scheduling
---------------
Cron syntax: "minute hour day month weekday" (standard 5-field cron).
A simple best-effort evaluator is used (no external cron library).
For production, replace with APScheduler or Celery Beat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import ExecutionPlan, Workflow
from app.db.monitoring_models import MonitoringRule
from app.db.session import AsyncSessionLocal
from app.schemas.monitoring import ALLOWED_FREQUENCIES, FREQUENCY_INTERVAL_MINUTES

logger = logging.getLogger(__name__)

# How often the scheduler wakes up to check for due evaluations (in seconds).
# Set to 5 minutes — granular enough for hourly checks without being wasteful.
TICK_INTERVAL_SECONDS = 60  # 1 minute; scheduled workflows use minute precision

# Flag to allow graceful shutdown
_running = False
_task: asyncio.Task | None = None


# ── Public API ────────────────────────────────────────────────────────────────

def compute_next_evaluation(frequency: str, from_time: datetime) -> datetime:
    """
    Compute the next evaluation time given a frequency and a reference time.
    Minimum granularity: 1 hour.
    """
    interval_minutes = FREQUENCY_INTERVAL_MINUTES.get(frequency, 1440)  # default daily
    return from_time + timedelta(minutes=interval_minutes)


async def start_scheduler() -> None:
    """
    Start the background monitoring scheduler.
    Called from the FastAPI lifespan event.
    """
    global _running, _task
    if _running:
        logger.info("Monitoring scheduler already running — skipping start")
        return
    _running = True
    _task = asyncio.create_task(_scheduler_loop(), name="monitoring-scheduler")
    logger.info("Monitoring scheduler started (tick interval: %ds)", TICK_INTERVAL_SECONDS)


async def stop_scheduler() -> None:
    """
    Stop the background monitoring scheduler.
    Called from the FastAPI lifespan shutdown event.
    """
    global _running, _task
    _running = False
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await asyncio.wait_for(_task, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        _task = None
    logger.info("Monitoring scheduler stopped")


def is_running() -> bool:
    return _running


# ── Scheduler loop ────────────────────────────────────────────────────────────

async def _scheduler_loop() -> None:
    """Main scheduler loop — runs until _running is set to False."""
    # Initial boot: initialise next_evaluation_at for any rules that don't have it
    await _initialise_rules()

    while _running:
        try:
            await _tick()
        except Exception as exc:
            logger.error("Monitoring scheduler tick error: %s", exc)
        # Sleep until next tick — break early if stopped
        for _ in range(TICK_INTERVAL_SECONDS):
            if not _running:
                break
            await asyncio.sleep(1)


async def _initialise_rules() -> None:
    """Set next_evaluation_at for any enabled rules that have none."""
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MonitoringRule).where(
                    MonitoringRule.enabled == True,  # noqa: E712
                    MonitoringRule.next_evaluation_at == None,  # noqa: E711
                )
            )
            rules = result.scalars().all()
            for rule in rules:
                rule.next_evaluation_at = compute_next_evaluation(
                    rule.evaluation_frequency, now
                )
            await session.commit()
            if rules:
                logger.info(
                    "Initialised next_evaluation_at for %d monitoring rule(s)", len(rules)
                )
    except Exception as exc:
        logger.error("Failed to initialise monitoring rules: %s", exc)


async def _tick() -> None:
    """
    One scheduler tick: find due monitoring rules and due scheduled workflows,
    then evaluate/execute them.
    """
    now = datetime.now(timezone.utc)

    # ── Monitoring rules ──────────────────────────────────────────────────────
    due_rules: list[tuple[str, str]] = []  # (rule_id, tenant_id)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MonitoringRule.id, MonitoringRule.tenant_id).where(
                    MonitoringRule.enabled == True,  # noqa: E712
                    MonitoringRule.is_locked == False,  # noqa: E712
                    MonitoringRule.next_evaluation_at <= now,
                )
            )
            due_rules = list(result.all())
    except Exception as exc:
        logger.error("Monitoring scheduler: failed to query due rules: %s", exc)

    if due_rules:
        logger.info("Monitoring scheduler: %d rule(s) due for evaluation", len(due_rules))

    # Evaluate each rule in a separate async task but sequentially to avoid
    # overwhelming the database connection pool. For production with many rules,
    # this could be parallelised with a semaphore.
    for rule_id, rule_tenant_id in due_rules:
        if not _running:
            break
        try:
            await _evaluate_one(rule_id, rule_tenant_id)
        except Exception as exc:
            logger.error(
                "Monitoring scheduler: evaluation of rule %s (tenant %s) failed: %s",
                rule_id, rule_tenant_id, exc,
            )

    # ── Scheduled workflows ───────────────────────────────────────────────────
    try:
        await _tick_workflows()
    except Exception as exc:
        logger.error("Workflow scheduler tick error: %s", exc)

    # ── Notification email outbox (consent re-checked per message) ────────────
    try:
        from app.services.notification_service import deliver_pending_emails
        async with AsyncSessionLocal() as session:
            counts = await deliver_pending_emails(session)
            await session.commit()
            if counts["sent"] or counts["failed"]:
                logger.info("Notification emails: %s", counts)
    except Exception as exc:
        logger.error("Notification email delivery error: %s", exc)


async def _evaluate_one(rule_id: str, tenant_id: str) -> None:
    """Evaluate a single rule in its own DB session."""
    from app.services.monitoring_engine import evaluate_rule
    async with AsyncSessionLocal() as session:
        result = await evaluate_rule(rule_id, tenant_id, session)
        await session.commit()
        logger.debug(
            "Monitoring rule %s (tenant %s) evaluation result: %s",
            rule_id, tenant_id, result,
        )


# ── Workflow Scheduler ────────────────────────────────────────────────────────

def _cron_is_due(cron_expr: str, now: datetime) -> bool:
    """
    Best-effort 5-field cron evaluator.
    Returns True if 'now' matches the cron expression.

    Fields: minute hour day_of_month month day_of_week
    Supports: * (any), */n (every n), single integers.
    Does NOT support: ranges (1-5), lists (1,3,5).

    For production, replace with a proper cron library (e.g. croniter).
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False
        m, h, dom, mon, dow = parts

        def _matches(field: str, value: int) -> bool:
            if field == "*":
                return True
            if field.startswith("*/"):
                step = int(field[2:])
                return value % step == 0
            return int(field) == value

        return (
            _matches(m, now.minute)
            and _matches(h, now.hour)
            and _matches(dom, now.day)
            and _matches(mon, now.month)
            and _matches(dow, now.weekday())
        )
    except Exception:
        return False


def _has_run_this_minute(last_run_at: datetime | None, now: datetime) -> bool:
    if not last_run_at:
        return False
    last_run_utc = (
        last_run_at.replace(tzinfo=timezone.utc)
        if last_run_at.tzinfo is None
        else last_run_at.astimezone(timezone.utc)
    )
    now_utc = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    return last_run_utc.strftime("%Y-%m-%d %H:%M") == now_utc.strftime("%Y-%m-%d %H:%M")


async def _tick_workflows() -> None:
    """
    One workflow tick (see ``services/workflow_runner``): recover interrupted
    runs, claim due scheduled runs under a unique slot (no duplicates), execute
    them through the normal agent path with the owner's permissions re-checked,
    and run any retries that have come due.
    """
    from app.services import workflow_runner

    try:
        stats = await workflow_runner.tick()
        if stats["claimed"] or stats["executed"] or stats["recovered"]:
            logger.info("Workflow scheduler tick: %s", stats)
    except Exception as exc:
        logger.error("Workflow scheduler tick failed: %s", type(exc).__name__)


async def _execute_workflow(workflow_id: str, tenant_id: str) -> None:
    """Run one workflow now through the shared runner (kept for existing callers)."""
    from app.services import workflow_runner

    await workflow_runner.run_now(workflow_id, tenant_id, requested_by="")
