"""
Meeting Room API (/api/v1/meetings).

Any signed-in member can start a meeting and sees their own; company administrators
see every meeting of their company. Everything is tenant-scoped. Agents act with the
permissions of the person who started the meeting (and the company's role/grant rules).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, is_admin_user
from app.core.prompt_guard import validate_user_prompt
from app.db.meeting_models import Meeting, MeetingMessage, MeetingTask
from app.db.models import User
from app.db.session import get_db
from app.services import meeting_service as ms

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])

_TERMINAL = {"completed", "partial", "failed", "cancelled"}


class MeetingCreate(BaseModel):
    objective: str = Field(..., min_length=3, max_length=2000)
    title: str = Field(default="", max_length=200)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class TaskOut(BaseModel):
    id: str
    key: str
    role_key: str
    role_name: str
    title: str
    instruction: str
    depends_on: list[str]
    status: str
    result: str
    plan_id: str | None
    pending_task_id: str | None
    started_at: datetime | None
    finished_at: datetime | None


class MessageOut(BaseModel):
    id: str
    seq: int
    sender_kind: str
    sender_name: str
    recipient_name: str
    kind: str
    task_id: str | None
    content: str
    created_at: datetime


class MeetingOut(BaseModel):
    id: str
    title: str
    objective: str
    status: str
    summary: str
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    task_count: int = 0
    completed_count: int = 0


class MeetingDetail(MeetingOut):
    tasks: list[TaskOut]
    messages: list[MessageOut]


def _task_out(t: MeetingTask) -> TaskOut:
    return TaskOut(id=t.id, key=t.key, role_key=t.role_key, role_name=t.role_name, title=t.title,
                   instruction=t.instruction, depends_on=ms._deps(t), status=t.status, result=t.result,
                   plan_id=t.plan_id, pending_task_id=t.pending_task_id, started_at=t.started_at, finished_at=t.finished_at)


async def _load(meeting_id: str, user: User, db: AsyncSession) -> Meeting:
    m = (await db.execute(select(Meeting).where(Meeting.id == meeting_id, Meeting.tenant_id == user.tenant_id))).scalar_one_or_none()
    if m is None or (m.created_by != user.id and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Meeting not found")          # same answer: no existence leak
    return m


async def _detail(m: Meeting, db: AsyncSession) -> MeetingDetail:
    tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == m.id, MeetingTask.tenant_id == m.tenant_id)
                              .order_by(MeetingTask.position))).scalars().all()
    msgs = (await db.execute(select(MeetingMessage).where(MeetingMessage.meeting_id == m.id, MeetingMessage.tenant_id == m.tenant_id)
                             .order_by(MeetingMessage.seq))).scalars().all()
    return MeetingDetail(
        id=m.id, title=m.title, objective=m.objective, status=m.status, summary=m.summary, created_by=m.created_by,
        created_at=m.created_at, finished_at=m.finished_at, task_count=len(tasks),
        completed_count=sum(1 for t in tasks if t.status == "completed"),
        tasks=[_task_out(t) for t in tasks],
        messages=[MessageOut(id=x.id, seq=x.seq, sender_kind=x.sender_kind, sender_name=x.sender_name,
                             recipient_name=x.recipient_name, kind=x.kind, task_id=x.task_id, content=x.content,
                             created_at=x.created_at) for x in msgs],
    )


@router.get("", response_model=list[MeetingOut])
async def list_meetings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[MeetingOut]:
    q = select(Meeting).where(Meeting.tenant_id == user.tenant_id)
    if not is_admin_user(user):
        q = q.where(Meeting.created_by == user.id)
    rows = (await db.execute(q.order_by(Meeting.created_at.desc()).limit(50))).scalars().all()
    # One grouped query for every meeting's task counts (was one query per meeting).
    counts: dict[str, list[int]] = {}
    if rows:
        from sqlalchemy import case, func
        grouped = (select(MeetingTask.meeting_id, func.count(),
                          func.sum(case((MeetingTask.status == "completed", 1), else_=0)))
                   .where(MeetingTask.tenant_id == user.tenant_id, MeetingTask.meeting_id.in_([m.id for m in rows]))
                   .group_by(MeetingTask.meeting_id))
        for mid, total, done in (await db.execute(grouped)).all():
            counts[mid] = [int(total), int(done or 0)]
    return [MeetingOut(id=m.id, title=m.title, objective=m.objective, status=m.status, summary=m.summary,
                       created_by=m.created_by, created_at=m.created_at, finished_at=m.finished_at,
                       task_count=counts.get(m.id, [0, 0])[0], completed_count=counts.get(m.id, [0, 0])[1])
            for m in rows]


@router.post("", response_model=MeetingDetail, status_code=201)
async def create_meeting(body: MeetingCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeetingDetail:
    validate_user_prompt(body.objective)
    try:
        m = await ms.create_meeting(db, user, body.objective.strip(), body.title.strip())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()                       # the background run reads committed rows
    ms.spawn(m.id)
    return await _detail(m, db)


@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(meeting_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeetingDetail:
    return await _detail(await _load(meeting_id, user, db), db)


@router.post("/{meeting_id}/messages", response_model=MeetingDetail)
async def post_message(meeting_id: str, body: MessageCreate, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> MeetingDetail:
    """Say something in the meeting: the coordinator turns it into follow-up tasks for the agents."""
    validate_user_prompt(body.content)
    m = await _load(meeting_id, user, db)
    if m.status == "cancelled":
        raise HTTPException(status_code=409, detail="This meeting was cancelled")
    if m.status in ("awaiting_approval", "waiting_setup"):
        raise HTTPException(status_code=409, detail="This meeting is paused; resolve the pending approval or setup first")
    if m.status == "planning":
        raise HTTPException(status_code=409, detail="The meeting is still being planned")
    await ms.add_message(db, m, "user", user.name or user.email, body.content.strip())
    roles = await ms.roster(db, m.tenant_id)
    if not roles:
        raise HTTPException(status_code=409, detail="No AI employee is available right now (all are paused).")
    await ms.append_plan(db, m, body.content.strip(), roles, context=m.summary or m.objective)
    was_terminal = m.status in _TERMINAL
    if was_terminal:
        m.status, m.finished_at = "queued", None
    await db.commit()
    if was_terminal:
        ms.spawn(m.id)                      # a running meeting picks the new tasks up on its next loop
    return await _detail(m, db)


@router.post("/{meeting_id}/cancel", response_model=MeetingDetail)
async def cancel_meeting(meeting_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeetingDetail:
    m = await _load(meeting_id, user, db)
    if m.status in _TERMINAL:
        raise HTTPException(status_code=409, detail=f"A meeting that is {m.status} cannot be cancelled")
    await ms.cancel_meeting(db, m, by=user.email or user.id)
    await db.commit()
    return await _detail(m, db)


@router.post("/{meeting_id}/resume", response_model=MeetingDetail)
async def resume_meeting(meeting_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeetingDetail:
    m = await _load(meeting_id, user, db)
    if m.status not in ("awaiting_approval", "waiting_setup"):
        raise HTTPException(status_code=409, detail="This meeting is not waiting for anything")
    outcome = await ms.resume_meeting(db, m)
    if outcome == "still_awaiting_approval":
        raise HTTPException(status_code=409, detail="The action is still waiting for an administrator's approval")
    await db.commit()
    ms.spawn(m.id)
    return await _detail(m, db)
