"""
Institutional Clerk API.

Any signed-in member: submit requests, see THEIR OWN requests, comment, cancel while open, download documents
issued for their own request.  Administrators: the whole company queue, status changes, assignment, internal
notes, drafting/issuing/voiding documents, extracting details from uploaded files.  Another company's data
is always a 404.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, is_admin_user, require_admin
from app.db.clerk_models import IssuedDocument, ServiceRequest
from app.db.models import User
from app.db.session import get_db
from app.services import clerk_service as cs

router = APIRouter(prefix="/api/v1/clerk", tags=["institutional-clerk"])


class RequestCreate(BaseModel):
    request_type: str
    title: str = Field(..., min_length=3, max_length=200)
    details: str = Field(default="", max_length=4000)
    fields: dict | None = None
    priority: str = "normal"
    due_date: str | None = None


class CommentBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    internal: bool = False


class StatusBody(BaseModel):
    status: str
    note: str = Field(default="", max_length=2000)


class AssignBody(BaseModel):
    assignee_id: str | None = None


class DraftBody(BaseModel):
    template_key: str
    fields: dict = Field(default_factory=dict)
    request_id: str | None = None
    title: str = Field(default="", max_length=200)


class VoidBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class EventOut(BaseModel):
    id: str
    kind: str
    actor_name: str
    body: str
    internal: bool
    created_at: datetime


class DocumentOut(BaseModel):
    id: str
    request_id: str | None
    template_key: str
    title: str
    status: str
    serial: str | None
    body: str
    fields: dict
    created_at: datetime
    issued_at: datetime | None


class RequestOut(BaseModel):
    id: str
    request_type: str
    title: str
    details: str
    fields: dict
    status: str
    priority: str
    requester_id: str
    requester_name: str
    assignee_id: str | None
    assignee_name: str
    due_date: str | None
    decision_note: str
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RequestDetail(RequestOut):
    events: list[EventOut]
    documents: list[DocumentOut]


def _fail(exc: cs.ClerkError):
    raise HTTPException(status_code=exc.status, detail=str(exc))


def _req_out(r: ServiceRequest) -> RequestOut:
    return RequestOut(id=r.id, request_type=r.request_type, title=r.title, details=r.details, fields=json.loads(r.fields_json or "{}"),
                      status=r.status, priority=r.priority, requester_id=r.requester_id, requester_name=r.requester_name,
                      assignee_id=r.assignee_id, assignee_name=r.assignee_name, due_date=r.due_date, decision_note=r.decision_note,
                      decided_at=r.decided_at, created_at=r.created_at, updated_at=r.updated_at)


def _doc_out(d: IssuedDocument) -> DocumentOut:
    return DocumentOut(id=d.id, request_id=d.request_id, template_key=d.template_key, title=d.title, status=d.status, serial=d.serial,
                       body=d.body, fields=json.loads(d.fields_json or "{}"), created_at=d.created_at, issued_at=d.issued_at)


async def _load(request_id: str, user: User, db: AsyncSession) -> ServiceRequest:
    r = await cs.get_request(db, user.tenant_id, request_id)
    if r is None or (r.requester_id != user.id and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Request not found")
    return r


async def _detail(r: ServiceRequest, user: User, db: AsyncSession) -> RequestDetail:
    await db.refresh(r)                         # server-side updated_at is expired after a flush
    admin = is_admin_user(user)
    events = await cs.events_of(db, r.tenant_id, r.id, include_internal=admin)
    q = select(IssuedDocument).where(IssuedDocument.tenant_id == r.tenant_id, IssuedDocument.request_id == r.id).order_by(IssuedDocument.created_at)
    docs = [d for d in (await db.execute(q)).scalars().all() if admin or d.status == "issued"]   # requesters never see drafts
    return RequestDetail(**_req_out(r).model_dump(),
                         events=[EventOut(id=e.id, kind=e.kind, actor_name=e.actor_name, body=e.body, internal=e.internal, created_at=e.created_at) for e in events],
                         documents=[_doc_out(d) for d in docs])


@router.get("/meta")
async def meta(user: User = Depends(get_current_user)) -> dict:
    return {"request_types": cs.REQUEST_TYPES, "statuses": list(cs.TRANSITIONS), "templates": cs.template_catalog() if is_admin_user(user) else []}


@router.post("/requests", response_model=RequestDetail, status_code=201)
async def create_request(body: RequestCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    try:
        r = await cs.create_request(db, user, body.request_type, body.title, body.details, body.fields, body.priority, body.due_date)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return await _detail(r, user, db)


@router.get("/requests", response_model=list[RequestOut])
async def list_requests(status: str | None = None, mine: bool = False, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> list[RequestOut]:
    q = select(ServiceRequest).where(ServiceRequest.tenant_id == user.tenant_id)
    if mine or not is_admin_user(user):
        q = q.where(ServiceRequest.requester_id == user.id)
    if status:
        q = q.where(ServiceRequest.status == status)
    q = q.order_by(ServiceRequest.created_at.desc()).limit(300)
    return [_req_out(r) for r in (await db.execute(q)).scalars().all()]


@router.get("/requests/{request_id}", response_model=RequestDetail)
async def get_request(request_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    return await _detail(await _load(request_id, user, db), user, db)


@router.post("/requests/{request_id}/comments", response_model=RequestDetail)
async def add_comment(request_id: str, body: CommentBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    r = await _load(request_id, user, db)
    try:
        cs.comment(db, r, user, body.body, is_admin_user(user), body.internal)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return await _detail(r, user, db)


@router.post("/requests/{request_id}/cancel", response_model=RequestDetail)
async def cancel_request(request_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    r = await _load(request_id, user, db)
    try:
        cs.requester_cancel(db, r, user)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return await _detail(r, user, db)


@router.post("/requests/{request_id}/status", response_model=RequestDetail)
async def set_status(request_id: str, body: StatusBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    r = await _load(request_id, admin, db)
    try:
        cs.change_status(db, r, body.status, admin, body.note)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return await _detail(r, admin, db)


@router.post("/requests/{request_id}/assign", response_model=RequestDetail)
async def assign(request_id: str, body: AssignBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> RequestDetail:
    r = await _load(request_id, admin, db)
    try:
        await cs.assign(db, r, admin, body.assignee_id)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return await _detail(r, admin, db)


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def draft_document(body: DraftBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> DocumentOut:
    req = None
    if body.request_id:
        req = await cs.get_request(db, admin.tenant_id, body.request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="Request not found")
    try:
        if body.template_key not in cs.TEMPLATES:
            raise cs.ClerkError("Unknown document template.")
        doc = await cs.draft_document(db, admin.tenant_id, body.template_key, body.fields, admin.email or admin.id, req, body.title)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return _doc_out(doc)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[DocumentOut]:
    q = select(IssuedDocument).where(IssuedDocument.tenant_id == admin.tenant_id).order_by(IssuedDocument.created_at.desc()).limit(300)
    return [_doc_out(d) for d in (await db.execute(q)).scalars().all()]


async def _document(doc_id: str, user: User, db: AsyncSession) -> IssuedDocument:
    q = select(IssuedDocument).where(IssuedDocument.id == doc_id, IssuedDocument.tenant_id == user.tenant_id)
    d = (await db.execute(q)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not is_admin_user(user):                                 # requester: only an ISSUED document for their OWN request
        own = None
        if d.request_id:
            r = await cs.get_request(db, user.tenant_id, d.request_id)
            own = r is not None and r.requester_id == user.id
        if not own or d.status != "issued":
            raise HTTPException(status_code=404, detail="Document not found")
    return d


@router.get("/documents/{doc_id}/download")
async def download_document(doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    d = await _document(doc_id, user, db)
    name = (d.serial or "draft").replace("/", "-")
    return Response(content=d.body, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.txt"'})


@router.post("/documents/{doc_id}/issue", response_model=DocumentOut)
async def issue_document(doc_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> DocumentOut:
    d = await _document(doc_id, admin, db)
    try:
        await cs.issue_document(db, d, admin)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return _doc_out(d)


@router.post("/documents/{doc_id}/void", response_model=DocumentOut)
async def void_document(doc_id: str, body: VoidBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> DocumentOut:
    d = await _document(doc_id, admin, db)
    try:
        cs.void_document(db, d, admin, body.reason)
    except cs.ClerkError as exc:
        _fail(exc)
    await db.commit()
    return _doc_out(d)


@router.post("/extract")
async def extract(file: UploadFile = File(...), admin: User = Depends(require_admin)) -> dict:
    data = await file.read(5 * 1024 * 1024 + 1)
    try:
        return await cs.extract_fields(file.filename or "", data)
    except cs.ClerkError as exc:
        _fail(exc)
