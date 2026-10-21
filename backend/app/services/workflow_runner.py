"""
Workflow execution: one reliable path for manual and scheduled runs.

Reuses the existing agent execution path (``execute_agent``): readiness gate,
role tool list, capability grants, planner, approvals, grounding.  A workflow
run is "this saved request, executed as this AI role, on behalf of this user",
so nothing about authorisation is re-implemented here.

Guarantees
* Duplicate prevention: a run row is claimed under UNIQUE(workflow_id, slot).
  The same scheduled minute can never run twice - across ticks, processes or
  restarts.  The claim to *start* is a conditional UPDATE, so two workers
  cannot both execute one row.
* Re-validation on EVERY run: workflow enabled, company active, the run-as
  user still exists in this tenant, is active and is still an administrator.
  Role grants and integration credentials are re-checked by the execution path.
* Honest outcomes: completed / failed / awaiting_approval / waiting_setup /
  skipped.  Only a completed plan is reported as completed.
* Retries are explicit: ``max_retries`` and ``retry_delay_minutes`` per workflow;
  only genuine failures are retried (not waiting_setup / approval / skipped).
* Recovery: a run left ``running`` by a crash/restart is failed with a clear
  reason, the workflow is released, and a retry is queued if the policy allows.
* Missed schedules are NOT replayed after downtime (no catch-up storm); the next
  due slot runs normally.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Company, User, Workflow
from app.db.session import AsyncSessionLocal
from app.db.workflow_run_models import WorkflowRun

logger = logging.getLogger(__name__)

RUN_TIMEOUT_MINUTES = 20            # a run "running" longer than this was interrupted
MAX_RETRY_LIMIT = 5
FAILURE_DELAY_CAP_MINUTES = 24 * 60
TERMINAL = {"completed", "failed", "skipped", "cancelled", "awaiting_approval", "waiting_setup"}


def _maker():
    # Looked up at call time so tests can substitute their own session factory.
    return AsyncSessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def slot_for(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def local_time(now: datetime, tz_name: str) -> datetime:
    try:
        return now.astimezone(ZoneInfo(tz_name or "UTC"))
    except Exception:
        return now.astimezone(timezone.utc)


def build_prompt(wf: Workflow) -> str:
    steps = json.loads(wf.steps_json or "[]")
    descriptions = [str(s.get("description", "")).strip() for s in steps if str(s.get("description", "")).strip()]
    instructions = "; ".join(descriptions[:5]) or (wf.description or "").strip() or wf.name
    return f"Scheduled workflow '{wf.name}': {instructions}"


# ── claiming ─────────────────────────────────────────────────────────────────

async def claim_run(
    session: AsyncSession, wf: Workflow, *, trigger: str, slot: str, attempt: int = 1,
    status: str = "queued", not_before: datetime | None = None, detail: str = "",
    requested_by: str = "",
) -> WorkflowRun | None:
    """Insert the run row; None means this slot was already claimed (a duplicate)."""
    run = WorkflowRun(
        id=str(uuid.uuid4()), tenant_id=wf.tenant_id, workflow_id=wf.id, trigger=trigger, slot=slot,
        attempt=attempt, status=status, not_before=not_before, detail=detail[:500], created_at=_now(),
        requested_by=requested_by or (wf.run_as_user_id or ""),
        finished_at=_now() if status in TERMINAL else None,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        return None
    return run


# ── re-validation ────────────────────────────────────────────────────────────

async def _revalidate(session: AsyncSession, wf: Workflow) -> tuple[User | None, str]:
    """(run-as user, "") when allowed to run, else (None, reason)."""
    if not wf.is_enabled:
        return None, "The workflow is disabled."
    company = await session.get(Company, wf.tenant_id)
    if company is None or not company.is_active:
        return None, "The company workspace is inactive."
    if not wf.run_as_user_id:
        return None, "No user is responsible for this workflow; re-save it as an administrator."
    user = await session.get(User, wf.run_as_user_id)
    if user is None or user.tenant_id != wf.tenant_id:
        return None, "The user who owns this workflow no longer exists in this company."
    if not user.is_active or user.status != "Active":
        return None, "The user who owns this workflow is deactivated."
    from app.core.auth import is_admin_user
    if not is_admin_user(user):
        return None, "The user who owns this workflow is no longer an administrator."
    return user, ""


# ── execution ────────────────────────────────────────────────────────────────

async def _finish(
    session: AsyncSession, run: WorkflowRun, wf: Workflow | None, status: str, detail: str,
    plan_id: str | None = None, pending_task_id: str | None = None,
) -> None:
    run.status = status
    run.detail = detail[:500]
    run.plan_id = plan_id
    run.pending_task_id = pending_task_id
    run.finished_at = _now()
    if wf is not None:
        wf.status = "idle" if status in ("skipped", "cancelled", "waiting_setup") else status
        wf.last_run_status = status
    if wf is not None:
        session.add(AuditLog(
            id=str(uuid.uuid4()), tenant_id=run.tenant_id, ai_employee_id=None, actor="workflow-runner",
            event=f"workflow '{wf.name[:80]}' run {run.attempt} ({run.trigger}) {status}",
            department="workflows", status="ok" if status == "completed" else "warning",
        ))
        if status == "failed":
            from app.services.notification_service import notify_admins
            await notify_admins(session, run.tenant_id, "workflow_failed", f"Workflow failed: {wf.name[:80]}",
                                (detail or "")[:300], severity="warning", related_id=run.id, related_type="workflow_run")


async def execute_run(run_id: str) -> str:
    """Run one queued run. Returns the final status (or the current one if not runnable)."""
    async with _maker()() as session:
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            return "missing"
        # Atomic start: only one worker can move queued -> running.
        started = await session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status == "queued")
            .values(status="running", started_at=_now())
        )
        await session.commit()
        if started.rowcount != 1:
            await session.refresh(run)
            return run.status
        await session.refresh(run)

        wf = (await session.execute(
            select(Workflow).where(Workflow.id == run.workflow_id, Workflow.tenant_id == run.tenant_id)
        )).scalar_one_or_none()
        if wf is None:
            await _finish(session, run, None, "skipped", "The workflow no longer exists.")
            await session.commit()
            return "skipped"

        user, reason = await _revalidate(session, wf)
        if user is None:
            await _finish(session, run, wf, "skipped", reason)
            await session.commit()
            logger.warning("Workflow %s run skipped: %s", wf.id, reason)
            return "skipped"

        wf.status = "running"
        wf.last_run_at = _now()
        await session.commit()

        status, detail, plan_id, pending_id = await _call_agent(session, wf, user)
        await _finish(session, run, wf, status, detail, plan_id, pending_id)
        if status == "failed":
            await _maybe_retry(session, wf, run)
        await session.commit()
        return status


async def _call_agent(session: AsyncSession, wf: Workflow, user: User):
    from app.api.routers.execution import execute_agent
    from app.schemas.blueprint import AgentBlueprint, AgentExecutionRequest

    request = AgentExecutionRequest(
        blueprint=AgentBlueprint(
            agent_id=f"workflow-{wf.id[:8]}", role_name=wf.role_name or "Workflow Agent",
            system_persona="Scheduled workflow run.", tenant_id=wf.tenant_id,
        ),
        user_prompt=build_prompt(wf),
        session_id=f"workflow:{wf.id}",
    )
    try:
        resp = await execute_agent(request=request, tenant_id=wf.tenant_id, db=session, user=user)
    except Exception as exc:  # noqa: BLE001
        reason = getattr(exc, "detail", None)
        text = reason if isinstance(reason, str) else type(exc).__name__
        logger.error("Workflow %s run failed: %s", wf.id, type(exc).__name__)
        return "failed", f"Execution error: {text}", None, None
    plan_status = resp.plan_status
    if plan_status == "completed":
        return "completed", (resp.message or "")[:300], resp.plan_id, None
    if plan_status == "awaiting_approval":
        return "awaiting_approval", "Waiting for an administrator's approval.", resp.plan_id, None
    if plan_status == "awaiting_setup":
        return "waiting_setup", (resp.message or "Integration setup is required.")[:300], None, resp.pending_task_id
    return "failed", ((resp.message or "")[:300] or f"The run ended with status '{plan_status}'."), resp.plan_id, None


# Step types that only read or reason. A run that got past any OTHER kind of step
# (an action: send, publish, create, change) may already have had an external effect,
# and re-running the whole request would repeat it.
SAFE_TO_REPEAT_STEP_TYPES = frozenset({"read", "analysis", "verify", "response", "tool"})


async def side_effects_may_have_happened(session: AsyncSession, wf: Workflow, run: WorkflowRun) -> bool:
    """True if this run's plan(s) executed - or began executing - any non-read step."""
    from app.db.models import ExecutionPlan, PlanStep

    started = _aware(run.started_at) or _aware(run.created_at)
    plans = (await session.execute(
        select(ExecutionPlan).where(
            ExecutionPlan.tenant_id == wf.tenant_id,
            ExecutionPlan.session_id == f"workflow:{wf.id}",
        )
    )).scalars().all()
    for plan in plans:
        created = _aware(plan.created_at)
        if run.plan_id and plan.id != run.plan_id and (started and created and created < started):
            continue
        if not run.plan_id and started and created and created < started - timedelta(seconds=5):
            continue
        steps = (await session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id, PlanStep.tenant_id == wf.tenant_id)
        )).scalars().all()
        for st in steps:
            if st.status in ("completed", "running", "awaiting_approval") and (st.step_type or "read") not in SAFE_TO_REPEAT_STEP_TYPES:
                return True
    return False


async def _maybe_retry(session: AsyncSession, wf: Workflow, run: WorkflowRun) -> None:
    allowed = max(0, min(int(wf.max_retries or 0), MAX_RETRY_LIMIT))
    if run.attempt > allowed:
        return
    if await side_effects_may_have_happened(session, wf, run):
        # Never repeat a run that may already have sent/created/changed something.
        run.detail = (run.detail + " Not retried automatically: an action step had already run, "
                      "and repeating it could duplicate an external effect.")[:500]
        return
    delay = min(max(1, int(wf.retry_delay_minutes or 15)) * run.attempt, FAILURE_DELAY_CAP_MINUTES)
    base = run.slot.split("#r")[0]
    await claim_run(
        session, wf, trigger="retry", slot=f"{base}#r{run.attempt + 1}", attempt=run.attempt + 1,
        status="queued", not_before=_now() + timedelta(minutes=delay),
        detail=f"Retry {run.attempt} of {allowed} after a failure.",
    )


# ── scheduler entry points ───────────────────────────────────────────────────

async def recover_interrupted(now: datetime | None = None) -> int:
    """Fail runs a crash/restart left `running`, release their workflows, queue retries."""
    now = now or _now()
    cutoff = now - timedelta(minutes=RUN_TIMEOUT_MINUTES)
    count = 0
    async with _maker()() as session:
        stale = (await session.execute(
            select(WorkflowRun).where(WorkflowRun.status == "running")
        )).scalars().all()
        for run in stale:
            started = _aware(run.started_at) or _aware(run.created_at) or now
            if started > cutoff:
                continue
            wf = await session.get(Workflow, run.workflow_id)
            await _finish(session, run, wf, "failed", "Interrupted: the server stopped or the run timed out.")
            if wf is not None:
                await _maybe_retry(session, wf, run)
            count += 1
        await session.commit()
    if count:
        logger.warning("Workflow recovery: %d interrupted run(s) marked failed", count)
    return count


async def reconcile_approvals() -> int:
    """
    A run paused for approval keeps its workflow blocked.  When the approval has
    been decided (the plan is no longer awaiting_approval), record the real
    outcome on the run and release the workflow.
    """
    from app.db.models import ExecutionPlan

    changed = 0
    async with _maker()() as session:
        waiting = (await session.execute(
            select(WorkflowRun).where(WorkflowRun.status == "awaiting_approval")
        )).scalars().all()
        for run in waiting:
            plan = await session.get(ExecutionPlan, run.plan_id) if run.plan_id else None
            if plan is None or plan.status == "awaiting_approval":
                continue
            final = "completed" if plan.status == "completed" else "failed"
            wf = await session.get(Workflow, run.workflow_id)
            await _finish(session, run, wf, final, f"Approval decided: plan {plan.status}.", run.plan_id)
            changed += 1
        await session.commit()
    return changed


def _due_now(wf: Workflow, now: datetime) -> bool:
    from app.services.monitoring_scheduler import _cron_is_due
    return bool(wf.schedule_cron) and _cron_is_due(wf.schedule_cron, local_time(now, wf.timezone))


async def tick(now: datetime | None = None) -> dict[str, int]:
    """One scheduler pass: recover, claim due scheduled runs, execute everything runnable."""
    now = now or _now()
    stats = {"recovered": 0, "claimed": 0, "executed": 0}
    stats["recovered"] = await recover_interrupted(now)
    await reconcile_approvals()
    to_run: list[str] = []
    async with _maker()() as session:
        workflows = (await session.execute(
            select(Workflow).where(
                Workflow.trigger == "scheduled", Workflow.is_enabled == True,  # noqa: E712
                Workflow.schedule_cron != None,  # noqa: E711
            )
        )).scalars().all()
        for wf in workflows:
            if not _due_now(wf, now):
                continue
            slot = slot_for(now)
            if wf.status in ("running", "awaiting_approval"):
                busy = "already running" if wf.status == "running" else "still waiting for approval"
                if await claim_run(session, wf, trigger="scheduled", slot=slot, status="skipped",
                                   detail=f"Skipped: the previous run is {busy}."):
                    stats["claimed"] += 1
                continue
            run = await claim_run(session, wf, trigger="scheduled", slot=slot)
            if run is not None:
                stats["claimed"] += 1
                to_run.append(run.id)
        await session.commit()
        queued = (await session.execute(
            select(WorkflowRun.id, WorkflowRun.not_before).where(WorkflowRun.status == "queued")
        )).all()
    for run_id, not_before in queued:
        if run_id not in to_run and (not_before is None or _aware(not_before) <= now):
            to_run.append(run_id)
    for run_id in to_run:
        await execute_run(run_id)
        stats["executed"] += 1
    return stats


async def run_now(wf_id: str, tenant_id: str, requested_by: str) -> tuple[WorkflowRun | None, str]:
    """Manual trigger: same path as a scheduled run. Returns (run, final status)."""
    async with _maker()() as session:
        wf = (await session.execute(
            select(Workflow).where(Workflow.id == wf_id, Workflow.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if wf is None:
            return None, "missing"
        if not wf.run_as_user_id:
            wf.run_as_user_id = requested_by      # legacy workflow: the triggering admin takes ownership
        run = await claim_run(session, wf, trigger="manual", slot=f"manual:{uuid.uuid4()}",
                              requested_by=requested_by)
        await session.commit()
        run_id = run.id if run else None
    if run_id is None:
        return None, "duplicate"
    status = await execute_run(run_id)
    async with _maker()() as session:
        return await session.get(WorkflowRun, run_id), status
