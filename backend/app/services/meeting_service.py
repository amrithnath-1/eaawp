"""
Meeting Room orchestration: real agent-to-agent delegation.

Flow
 1. ``plan_meeting``  - a coordinator (LLM) splits the objective into subtasks and
                        assigns each to an AI role that exists for this company.
                        If the model is unavailable or answers badly, the whole
                        objective is assigned to one role and the meeting says so.
 2. ``run_meeting``   - executes subtasks in dependency order. Each one runs through
                        the SAME governed pipeline as a normal chat (``execute_agent``):
                        server-side role config, integration grants, readiness gate,
                        approvals for guarded actions - as the meeting's creator.
                        Results of finished subtasks are handed to the agents that
                        depend on them (that hand-over is the agent-to-agent delegation).
 3. Every delegation, result, pause and summary is stored as a message.

Safety properties (tested): cancellation stops further subtasks; a subtask never runs
unless its dependencies completed; a paused (approval / setup) meeting resumes
without repeating completed subtasks; the creator is re-validated before each subtask;
nothing the agents return is invented by the coordinator summary.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.meeting_models import Meeting, MeetingMessage, MeetingTask
from app.db.models import Company, ExecutionPlan, RoleConfiguration, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

MAX_TASKS = 6
LEAD_FIRST = ["DIGITAL_MARKETING_MANAGER"]          # default assignee when the coordinator is unavailable
BUILT_IN_ROLES = [
    "SALES_DEVELOPMENT_REP", "FINANCIAL_ANALYST", "HR_BUSINESS_PARTNER", "CUSTOMER_SUCCESS_MANAGER",
    "OPERATIONS_ANALYST", "DATA_INTELLIGENCE_ANALYST",
]
UPSTREAM_CHARS = 1500
RESULT_CHARS = 4000
STALE_MINUTES = 30
TERMINAL_TASK = {"completed", "failed", "skipped", "cancelled"}
_background: set[asyncio.Task] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _maker():
    return AsyncSessionLocal


def spawn(meeting_id: str) -> None:
    """Start a meeting run in the background (the API returns immediately)."""
    task = asyncio.get_running_loop().create_task(run_meeting(meeting_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


# ── roster & planning ────────────────────────────────────────────────────────
async def roster(db: AsyncSession, tenant_id: str) -> list[dict]:
    """The roles this company's coordinator may delegate to."""
    from app.api.routers.role_config import _get_or_seed

    # The platform's built-in roles always exist for a company (created on first use); roles the
    # company added itself are included too. Roles of other companies never appear (tenant filter).
    for key in LEAD_FIRST + BUILT_IN_ROLES:
        await _get_or_seed(key, tenant_id, db)
    rows = (await db.execute(
        select(RoleConfiguration).where(RoleConfiguration.tenant_id == tenant_id)
        .order_by(RoleConfiguration.role_key)
    )).scalars().all()
    from app.services.employee_lifecycle import employee_is_blocked
    rows = [r for r in rows if not await employee_is_blocked(db, tenant_id, r.role_key)]    # paused employees get no work
    rows = sorted(rows, key=lambda r: (r.role_key not in LEAD_FIRST, r.role_key))
    return [
        {"role_key": r.role_key, "role_name": r.role_name or r.role_key.replace("_", " ").title(),
         "description": (r.description or "")[:200]}
        for r in rows
    ]


_COORD_SYSTEM = (
    "You are the coordinator of a meeting between AI employees of one company. "
    "Split the objective into at most {n} concrete subtasks and assign each to exactly one of the "
    "listed roles. A subtask may depend on earlier subtasks (its assignee will receive their results). "
    "Only assign work a role can plausibly do; do not invent data or results. "
    "Reply with JSON only: {{\"tasks\":[{{\"key\":\"t1\",\"role_key\":\"...\",\"title\":\"...\","
    "\"instruction\":\"...\",\"depends_on\":[]}}]}}"
)


def parse_plan(raw: str, roles: list[dict], limit: int = MAX_TASKS, prefix: str = "t") -> list[dict] | None:
    """Validate the coordinator's JSON. Returns None if it is unusable."""
    try:
        text = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip())
        text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        items = data["tasks"]
        if not isinstance(items, list) or not items:
            return None
    except Exception:  # noqa: BLE001
        return None
    by_key = {r["role_key"]: r for r in roles}
    out: list[dict] = []
    seen: set[str] = set()
    for i, it in enumerate(items[:limit]):
        if not isinstance(it, dict):
            return None
        role = by_key.get(str(it.get("role_key", "")))
        instruction = str(it.get("instruction", "")).strip()
        if role is None or not instruction:
            return None                                     # never silently reassign to a different role
        key = f"{prefix}{i + 1}"
        deps = [d for d in (it.get("depends_on") or []) if isinstance(d, str)]
        remap = {str(items[j].get("key", f"t{j + 1}")): f"{prefix}{j + 1}" for j in range(min(i, len(items)))}
        deps = [remap[d] for d in deps if d in remap]       # earlier tasks only -> no cycles
        out.append({"key": key, "role_key": role["role_key"], "role_name": role["role_name"],
                    "title": (str(it.get("title", "")).strip() or instruction)[:200],
                    "instruction": instruction[:2000], "depends_on": sorted(set(deps))})
        seen.add(key)
    return out


async def plan_tasks(objective: str, roles: list[dict], context: str = "", prefix: str = "t") -> tuple[list[dict], bool]:
    """Returns (tasks, used_fallback)."""
    from app.llm.gateway import get_llm_gateway
    from langchain_core.messages import HumanMessage, SystemMessage

    listing = "\n".join(f"- {r['role_key']}: {r['role_name']} - {r['description']}" for r in roles)
    human = f"Roles:\n{listing}\n\n" + (f"Meeting so far:\n{context[:1500]}\n\n" if context else "") + f"Objective: {objective}"
    try:
        model = get_llm_gateway().get_chat_model(temperature=0)
        resp = await model.ainvoke([SystemMessage(content=_COORD_SYSTEM.format(n=MAX_TASKS)), HumanMessage(content=human)])
        plan = parse_plan(resp.content if isinstance(resp.content, str) else "", roles, prefix=prefix)
        if plan:
            return plan, False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Meeting coordinator unavailable: %s", type(exc).__name__)
    lead = roles[0]
    return [{"key": f"{prefix}1", "role_key": lead["role_key"], "role_name": lead["role_name"],
             "title": objective[:200], "instruction": objective[:2000], "depends_on": []}], True


# ── persistence helpers ──────────────────────────────────────────────────────
async def add_message(db: AsyncSession, m: Meeting, sender_kind: str, sender_name: str, content: str,
                      kind: str = "message", recipient: str = "", task_id: str | None = None) -> MeetingMessage:
    seq = (await db.execute(
        select(func.coalesce(func.max(MeetingMessage.seq), 0)).where(MeetingMessage.meeting_id == m.id, MeetingMessage.tenant_id == m.tenant_id)
    )).scalar_one() + 1
    msg = MeetingMessage(id=str(uuid.uuid4()), meeting_id=m.id, tenant_id=m.tenant_id, seq=seq,
                         sender_kind=sender_kind, sender_name=sender_name[:128], recipient_name=recipient[:128],
                         kind=kind, task_id=task_id, content=content[:RESULT_CHARS], created_at=_now())
    db.add(msg)
    await db.flush()
    return msg


async def create_meeting(db: AsyncSession, user: User, objective: str, title: str = "") -> Meeting:
    """Create + plan. The caller starts the run (``spawn``) after committing."""
    roles = await roster(db, user.tenant_id)
    if not roles:
        raise ValueError("No AI employee is available right now (all are paused).")
    m = Meeting(id=str(uuid.uuid4()), tenant_id=user.tenant_id, title=(title or objective)[:200],
                objective=objective, status="planning", created_by=user.id)
    db.add(m)
    await db.flush()
    await add_message(db, m, "user", user.name or user.email, objective, kind="message")
    await append_plan(db, m, objective, roles)
    m.status = "queued"
    await db.flush()
    return m


async def append_plan(db: AsyncSession, m: Meeting, request_text: str, roles: list[dict], context: str = "") -> list[MeetingTask]:
    existing = (await db.execute(select(func.count()).select_from(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id))).scalar_one()
    prefix = "t" if existing == 0 else f"f{existing}_"
    plan, fallback = await plan_tasks(request_text, roles, context, prefix=prefix)
    if fallback:
        await add_message(db, m, "coordinator", "Coordinator", "I could not split this up automatically, so I am "
                          f"assigning the whole request to {plan[0]['role_name']}.", kind="status")
    created: list[MeetingTask] = []
    for i, t in enumerate(plan):
        row = MeetingTask(id=str(uuid.uuid4()), meeting_id=m.id, tenant_id=m.tenant_id, position=existing + i,
                          key=t["key"], role_key=t["role_key"], role_name=t["role_name"], title=t["title"],
                          instruction=t["instruction"], depends_on_json=json.dumps(t["depends_on"]), status="pending")
        db.add(row)
        created.append(row)
        await add_message(db, m, "coordinator", "Coordinator", f"{t['title']}\n\n{t['instruction']}", kind="delegation",
                          recipient=t["role_name"], task_id=row.id)
    await db.flush()
    return created


# ── execution ────────────────────────────────────────────────────────────────
def _deps(task: MeetingTask) -> list[str]:
    try:
        return list(json.loads(task.depends_on_json or "[]"))
    except ValueError:
        return []


def build_prompt(m: Meeting, task: MeetingTask, upstream: list[MeetingTask]) -> str:
    parts = [f"Meeting objective: {m.objective}", f"Your assignment - {task.title}:\n{task.instruction}"]
    if upstream:
        parts.append("Results from teammates that you build on (treat as reported by them, not verified by you):")
        for u in upstream:
            parts.append(f"[{u.role_name} - {u.title}]\n{(u.result or '')[:UPSTREAM_CHARS]}")
    parts.append("Use only data from your tools or the teammate results above. If you cannot get data, say so plainly.")
    return "\n\n".join(parts)


async def _call_role(db: AsyncSession, m: Meeting, task: MeetingTask, user: User, prompt: str):
    from app.api.routers.execution import execute_agent
    from app.schemas.blueprint import AgentBlueprint, AgentExecutionRequest

    req = AgentExecutionRequest(
        blueprint=AgentBlueprint(agent_id=f"meeting-{m.id[:8]}", role_name=task.role_name, role_key=task.role_key,
                                 system_persona="Meeting participant.", tenant_id=m.tenant_id),
        user_prompt=prompt, session_id=f"meeting:{m.id}",
    )
    try:
        resp = await execute_agent(request=req, tenant_id=m.tenant_id, db=db, user=user)
    except Exception as exc:  # noqa: BLE001
        reason = getattr(exc, "detail", None)
        text = reason if isinstance(reason, str) else type(exc).__name__
        logger.error("Meeting %s task %s failed: %s", m.id, task.key, type(exc).__name__)
        return "failed", f"Execution error: {text}", None, None
    status = resp.plan_status
    if status == "completed" or (status is None and resp.message):
        return "completed", resp.message or "", resp.plan_id, None
    if status == "awaiting_approval":
        return "awaiting_approval", resp.message or "Waiting for an administrator's approval.", resp.plan_id, None
    if status == "awaiting_setup":
        return "waiting_setup", resp.message or "Integration setup is required.", None, resp.pending_task_id
    return "failed", resp.message or f"The task ended with status '{status}'.", resp.plan_id, None


async def _set_meeting_status(db: AsyncSession, m: Meeting, status: str, only_if: str = "running") -> bool:
    res = await db.execute(update(Meeting).where(Meeting.id == m.id, Meeting.tenant_id == m.tenant_id, Meeting.status == only_if)
                           .values(status=status, updated_at=_now(),
                                   finished_at=_now() if status in ("completed", "partial", "failed", "cancelled") else None))
    await db.commit()
    return res.rowcount == 1


async def run_meeting(meeting_id: str) -> str:
    """Run every runnable subtask. Returns the meeting's status when it stops."""
    async with _maker()() as db:
        claimed = await db.execute(update(Meeting).where(
            Meeting.id == meeting_id, Meeting.status.in_(["queued", "planning"])
        ).values(status="running", updated_at=_now()))
        await db.commit()
        m = await db.get(Meeting, meeting_id)
        if m is None:
            return "missing"
        if claimed.rowcount != 1:
            return m.status                                    # someone else is running it, or it is paused/finished

        while True:
            await db.refresh(m)
            if m.status != "running":                          # cancelled (or recovered) while we worked
                return m.status
            tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id).order_by(MeetingTask.position))).scalars().all()
            by_key = {t.key: t for t in tasks}
            progressed = False
            for t in tasks:                                    # a task whose dependency did not complete never runs
                if t.status == "pending" and any(by_key.get(d) is None or by_key[d].status in ("failed", "skipped", "cancelled") for d in _deps(t)):
                    t.status, t.finished_at = "skipped", _now()
                    t.result = "Skipped because a task it depends on did not complete."
                    await add_message(db, m, "system", "System", f"{t.role_name}: '{t.title}' skipped - a dependency did not complete.",
                                      kind="status", task_id=t.id)
                    progressed = True
            nxt = next((t for t in tasks if t.status == "pending" and all(by_key[d].status == "completed" for d in _deps(t))), None)
            if nxt is None:
                await db.commit()
                if progressed:
                    continue
                break
            user = await db.get(User, m.created_by)
            if user is None or not user.is_active or user.tenant_id != m.tenant_id:
                for t in tasks:
                    if t.status == "pending":
                        t.status, t.finished_at, t.result = "skipped", _now(), "The meeting's owner is no longer an active member."
                await add_message(db, m, "system", "System", "Stopped: the person who started this meeting is no longer an active member.", kind="status")
                await db.commit()
                break
            nxt.status, nxt.started_at = "running", _now()
            await db.commit()
            upstream = [by_key[d] for d in _deps(nxt)]
            status, text, plan_id, pending_id = await _call_role(db, m, nxt, user, build_prompt(m, nxt, upstream))
            await db.refresh(m)
            if m.status != "running":                          # cancelled during execution: record, do not continue
                nxt.status = "cancelled" if status != "completed" else "completed"
                nxt.result, nxt.finished_at, nxt.plan_id = text[:RESULT_CHARS], _now(), plan_id
                await db.commit()
                return m.status
            nxt.status, nxt.result, nxt.plan_id, nxt.pending_task_id = status, text[:RESULT_CHARS], plan_id, pending_id
            if status in TERMINAL_TASK:
                nxt.finished_at = _now()
            await add_message(db, m, "agent", nxt.role_name, text, kind="result" if status == "completed" else "status", task_id=nxt.id)
            await db.commit()
            if status in ("awaiting_approval", "waiting_setup"):
                await _set_meeting_status(db, m, status)
                return status

        return await _finalize(db, m)


async def _finalize(db: AsyncSession, m: Meeting) -> str:
    await db.refresh(m)
    if m.status != "running":
        return m.status
    tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id).order_by(MeetingTask.position))).scalars().all()
    done = [t for t in tasks if t.status == "completed"]
    if tasks and len(done) == len(tasks):
        final = "completed"
    elif done:
        final = "partial"
    else:
        final = "failed"
    summary = await summarise(m, tasks)
    m.summary = summary
    await add_message(db, m, "coordinator", "Coordinator", summary, kind="summary")
    await db.commit()
    await _set_meeting_status(db, m, final)
    return final


async def summarise(m: Meeting, tasks: list[MeetingTask]) -> str:
    """Summary built ONLY from stored task results (the model may not add facts)."""
    lines = []
    for t in tasks:
        body = (t.result or "").strip().replace("\n", " ")[:400]
        lines.append(f"- {t.role_name} - {t.title} [{t.status}]: {body}")
    fallback = "Outcome of each task:\n" + "\n".join(lines)
    if not any(t.status == "completed" for t in tasks):
        return fallback
    try:
        from app.llm.gateway import get_llm_gateway
        from langchain_core.messages import HumanMessage, SystemMessage

        model = get_llm_gateway().get_chat_model(temperature=0)
        resp = await model.ainvoke([
            SystemMessage(content="You are the meeting coordinator. Write a short summary of the meeting for the user using ONLY "
                                  "the task results below. Do not add facts, figures or recommendations that are not in them. "
                                  "Say clearly which tasks did not complete."),
            HumanMessage(content=f"Objective: {m.objective}\n\n" + "\n".join(lines)),
        ])
        text = resp.content if isinstance(resp.content, str) else ""
        return text.strip()[:RESULT_CHARS] or fallback
    except Exception as exc:  # noqa: BLE001
        logger.warning("Meeting summary model unavailable: %s", type(exc).__name__)
        return fallback


# ── cancel / resume / recovery ───────────────────────────────────────────────
async def cancel_meeting(db: AsyncSession, m: Meeting, by: str) -> None:
    """Stop the meeting; reject any plan that is waiting for approval so it cannot run later."""
    from app.services.planner import reject_plan

    tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id))).scalars().all()
    for t in tasks:
        if t.status == "awaiting_approval" and t.plan_id:
            await reject_plan(plan_id=t.plan_id, tenant_id=m.tenant_id, reviewed_by=by, db=db)
        if t.status == "waiting_setup" and t.pending_task_id:
            from app.db.pending_task_models import PendingTask
            pt = await db.get(PendingTask, t.pending_task_id)
            if pt is not None and pt.tenant_id == m.tenant_id and pt.status == "waiting_setup":
                pt.status = "cancelled"
        if t.status in ("pending", "awaiting_approval", "waiting_setup"):
            t.status, t.finished_at = "cancelled", _now()
    m.status, m.finished_at = "cancelled", _now()
    await add_message(db, m, "system", "System", "Meeting cancelled. No further tasks will run.", kind="status")
    await db.flush()


async def resume_meeting(db: AsyncSession, m: Meeting) -> str:
    """After an approval was decided or setup completed. Never repeats completed tasks."""
    tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id).order_by(MeetingTask.position))).scalars().all()
    for t in tasks:
        if t.status == "awaiting_approval" and t.plan_id:
            plan = await db.get(ExecutionPlan, t.plan_id)
            if plan is None or plan.tenant_id != m.tenant_id:
                t.status, t.result = "failed", "The pending action could not be found."
            elif plan.status == "awaiting_approval":
                return "still_awaiting_approval"
            elif plan.status == "completed":
                t.status, t.result, t.finished_at = "completed", (plan.final_message or "")[:RESULT_CHARS], _now()
                await add_message(db, m, "agent", t.role_name, t.result, kind="result", task_id=t.id)
            else:
                t.status, t.finished_at = "failed", _now()
                t.result = (plan.final_message or f"The action ended as '{plan.status}'.")[:RESULT_CHARS]
                await add_message(db, m, "system", "System", f"{t.role_name}: {t.result}", kind="status", task_id=t.id)
        elif t.status == "waiting_setup":
            t.status = "pending"                                # the readiness gate re-checks when it runs
    await db.flush()
    if m.status in ("awaiting_approval", "waiting_setup"):
        m.status = "queued"
        await db.flush()
    return "queued"


async def recover_interrupted() -> int:
    """Startup: a meeting still 'running' long after its last update lost its worker."""
    cutoff = _now() - timedelta(minutes=STALE_MINUTES)
    n = 0
    async with _maker()() as db:
        stuck = (await db.execute(select(Meeting).where(Meeting.status == "running"))).scalars().all()
        for m in stuck:
            upd = m.updated_at if m.updated_at.tzinfo else m.updated_at.replace(tzinfo=timezone.utc)
            if upd > cutoff:
                continue
            mtasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id))).scalars().all()
            for t in mtasks:
                if t.status == "running":
                    t.status, t.finished_at, t.result = "failed", _now(), "Interrupted by a server restart."
                elif t.status == "pending":
                    t.status, t.finished_at, t.result = "skipped", _now(), "Not run: the meeting was interrupted."
            m.status, m.finished_at = "failed", _now()
            await add_message(db, m, "system", "System", "The server restarted while this meeting was running. Start a new meeting to retry.", kind="status")
            n += 1
        await db.commit()
    return n
