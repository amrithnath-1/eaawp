"""
Activity, Tasks and Insights for the selected AI employee, built from records the platform really keeps.

Nothing is invented: every item is a stored execution plan, approval request, saved setup task, scheduled workflow or
Meeting Room task, with its real timestamp and status. Administrators see the company's items for this AI employee;
everyone else sees only the items that came from their own conversations, meetings and requests.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import is_admin_user
from app.db.models import ActionAudit, ApprovalRequest, ExecutionPlan, PlanStep, User, Workflow

LIMIT = 30
_DATA_STEP_TYPES = {"read"}


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _excerpt(text: str, n: int = 280) -> str:
    text = " ".join((text or "").replace("#", " ").replace("*", "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


async def _selected_role(db: AsyncSession, user: User) -> str | None:
    from app.services.workspaces import _selection
    row = await _selection(db, user)
    return row.role_key if row else None


async def _own_sessions(db: AsyncSession, user: User) -> list[str]:
    from app.db.conversation_models import Conversation
    return list((await db.execute(select(Conversation.id).where(
        Conversation.tenant_id == user.tenant_id, Conversation.user_id == user.id))).scalars().all())


async def _plans(db: AsyncSession, user: User, role_key: str, statuses: tuple[str, ...] | None = None) -> list[ExecutionPlan]:
    stmt = select(ExecutionPlan).where(ExecutionPlan.tenant_id == user.tenant_id, ExecutionPlan.role_key == role_key)
    if statuses:
        stmt = stmt.where(ExecutionPlan.status.in_(statuses))
    if not is_admin_user(user):
        stmt = stmt.where(ExecutionPlan.session_id.in_(await _own_sessions(db, user)))
    return list((await db.execute(stmt.order_by(ExecutionPlan.created_at.desc()).limit(LIMIT))).scalars().all())


async def _requesters(db: AsyncSession, tenant_id: str, plans: list[ExecutionPlan]) -> dict[str, str]:
    """Who each plan was for: the conversation's owner, or the kind of unattended run."""
    from app.db.conversation_models import Conversation
    sessions = [p.session_id for p in plans if p.session_id]
    owners = dict((await db.execute(select(Conversation.id, Conversation.user_id).where(
        Conversation.tenant_id == tenant_id, Conversation.id.in_(sessions)))).all()) if sessions else {}
    names = dict((await db.execute(select(User.id, User.name).where(
        User.tenant_id == tenant_id, User.id.in_(list(owners.values()))))).all()) if owners else {}
    out = {}
    for p in plans:
        sid = p.session_id or ""
        if sid in owners:
            out[p.id] = names.get(owners[sid], "a team member")
        elif sid.startswith("workflow:"):
            out[p.id] = "scheduled workflow"
        elif sid.startswith("monitoring-"):
            out[p.id] = "monitoring rule"
        elif sid.startswith("meeting"):
            out[p.id] = "Meeting Room"
        else:
            out[p.id] = "—"
    return out


async def activity(db: AsyncSession, user: User) -> dict:
    role_key = await _selected_role(db, user)
    if role_key is None:
        return {"role_key": None, "items": []}
    plans = await _plans(db, user, role_key)
    who = await _requesters(db, user.tenant_id, plans)
    items = [{
        "id": p.id, "at": _iso(p.created_at), "kind": "run", "status": p.status,
        "title": _excerpt(p.objective, 140), "detail": f"for {who.get(p.id, '—')} · {p.completed_steps}/{p.total_steps} steps",
    } for p in plans]
    return {"role_key": role_key, "scope": "company" if is_admin_user(user) else "mine", "items": items}


async def tasks(db: AsyncSession, user: User) -> dict:
    """Work that is waiting or scheduled: approvals, saved setup requests, scheduled workflows, delegated meeting tasks."""
    from app.api.routers.execution import _blueprint_role_key
    from app.db.meeting_models import Meeting, MeetingTask
    from app.db.pending_task_models import PendingTask

    role_key = await _selected_role(db, user)
    if role_key is None:
        return {"role_key": None, "items": []}
    admin = is_admin_user(user)
    items: list[dict] = []

    pend = (await db.execute(
        select(ApprovalRequest, ActionAudit.tool_name)
        .join(ActionAudit, ActionAudit.approval_request_id == ApprovalRequest.id)
        .where(ApprovalRequest.tenant_id == user.tenant_id, ActionAudit.tenant_id == user.tenant_id,
               ApprovalRequest.status == "pending", ActionAudit.role_key == role_key)
        .order_by(ApprovalRequest.created_at.desc()).limit(LIMIT))).all()
    for a, tool in pend:
        items.append({"id": a.id, "at": _iso(a.created_at), "kind": "approval", "status": "awaiting_approval",
                      "title": f"Approval needed: {tool.replace('_', ' ')}",
                      "detail": "You can approve it in Approvals." if admin else "Waiting for an administrator."})

    q = select(PendingTask).where(PendingTask.tenant_id == user.tenant_id, PendingTask.role_key == role_key,
                                  PendingTask.status == "waiting_setup")
    if not admin:
        q = q.where(PendingTask.user_id == user.id)
    for t in (await db.execute(q.order_by(PendingTask.created_at.desc()).limit(LIMIT))).scalars().all():
        items.append({"id": t.id, "at": _iso(t.created_at), "kind": "setup", "status": "waiting_setup",
                      "title": _excerpt(t.prompt, 140), "detail": "Saved until an integration is set up."})

    if admin:
        wq = (select(Workflow).where(Workflow.tenant_id == user.tenant_id, Workflow.is_enabled == True)  # noqa: E712
              .order_by(Workflow.updated_at.desc()).limit(LIMIT))
        for w in (await db.execute(wq)).scalars().all():
            if _blueprint_role_key(w.role_name or "") != role_key:
                continue
            sched = f"schedule {w.schedule_cron} ({w.timezone})" if w.trigger == "scheduled" and w.schedule_cron else w.trigger
            last = f"last run {w.last_run_status}" if w.last_run_status else "not run yet"
            items.append({"id": w.id, "at": _iso(w.last_run_at or w.created_at), "kind": "workflow",
                          "status": w.status, "title": w.name, "detail": f"{sched} · {last}"})

    mq = (select(MeetingTask, Meeting.title)
          .join(Meeting, Meeting.id == MeetingTask.meeting_id)
          .where(MeetingTask.tenant_id == user.tenant_id, Meeting.tenant_id == user.tenant_id,
                 MeetingTask.role_key == role_key,
                 MeetingTask.status.in_(("pending", "running", "awaiting_approval", "waiting_setup"))))
    if not admin:
        mq = mq.where(Meeting.created_by == user.id)
    for mt, mtitle in (await db.execute(mq.limit(LIMIT))).all():
        items.append({"id": mt.id, "at": _iso(mt.started_at), "kind": "meeting_task", "status": mt.status,
                      "title": mt.title or _excerpt(mt.instruction, 140), "detail": f"Meeting: {mtitle}"})

    items.sort(key=lambda i: i["at"] or "", reverse=True)
    return {"role_key": role_key, "scope": "company" if admin else "mine", "items": items[:LIMIT]}


async def insights(db: AsyncSession, user: User) -> dict:
    """Completed runs whose answer was built on data a tool actually read, with the tools as sources."""
    role_key = await _selected_role(db, user)
    if role_key is None:
        return {"role_key": None, "items": []}
    plans = await _plans(db, user, role_key, ("completed",))
    if not plans:
        return {"role_key": role_key, "items": []}
    steps = (await db.execute(select(PlanStep).where(
        PlanStep.tenant_id == user.tenant_id, PlanStep.plan_id.in_([p.id for p in plans]),
        PlanStep.status == "completed"))).scalars().all()
    by_plan: dict[str, list[PlanStep]] = {}
    for s in steps:
        by_plan.setdefault(s.plan_id, []).append(s)
    items = []
    for p in plans:
        read = [s for s in by_plan.get(p.id, []) if s.step_type in _DATA_STEP_TYPES and s.tool_name]
        if not read:
            continue                                     # an answer with no data behind it is not an insight
        sources = list(dict.fromkeys(_source_label(s.tool_name) for s in read))
        items.append({"id": p.id, "at": _iso(p.created_at), "kind": "insight", "status": p.status,
                      "title": _excerpt(p.objective, 140), "detail": _excerpt(p.final_message, 320), "sources": sources})
    return {"role_key": role_key, "scope": "company" if is_admin_user(user) else "mine", "items": items}


def _source_label(tool_name: str) -> str:
    from app.tools.dynamic_tool import is_dynamic_tool_key
    if is_dynamic_tool_key(tool_name):
        cap = tool_name.split("_", 2)[-1] if tool_name.count("_") >= 2 else tool_name
        return f"Integration: {cap.replace('_', ' ')}"
    return tool_name.replace("_", " ")
