"""
Datasets (CSV/XLSX uploads) and saved analysis reports.

Upload / delete / restrict: administrators. Analyse / list / save reports: any signed-in member of the
company, except RESTRICTED datasets and their reports, which only administrators can see (others get 404).
Everything is tenant-scoped. Numbers always come from the deterministic engine; saving a report re-runs
the spec on the server and never trusts a client-supplied result.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, is_admin_user, require_admin
from app.core.prompt_guard import validate_user_prompt
from app.db.dataset_models import AnalysisReport, Dataset
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.services import analysis_engine as eng
from app.services import analysis_service as svc
from app.services import dataset_service as ds_svc

router = APIRouter(prefix="/api/v1", tags=["data-analyst"])
MAX_DATASETS = 50
MAX_REPORTS = 500


class DatasetOut(BaseModel):
    id: str
    name: str
    filename: str
    row_count: int
    size_bytes: int
    is_restricted: bool
    columns: list[dict]
    created_at: datetime


class DatasetDetail(DatasetOut):
    preview: list[list]


class AnalyzeBody(BaseModel):
    question: str | None = Field(default=None, max_length=1000)
    spec: dict | None = None


class AnalysisOut(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    chart: dict
    source: str
    notes: list[str]
    spec: dict
    narrative: str
    narrative_source: str


class RestrictBody(BaseModel):
    is_restricted: bool


class ReportBody(BaseModel):
    dataset_id: str
    title: str = Field(..., min_length=1, max_length=200)
    question: str = Field(default="", max_length=1000)
    spec: dict


class ReportOut(BaseModel):
    id: str
    dataset_id: str | None
    dataset_name: str
    title: str
    question: str
    result: dict
    narrative: str
    narrative_source: str
    is_restricted: bool
    created_by: str
    created_at: datetime


def _dataset_out(d: Dataset) -> DatasetOut:
    return DatasetOut(id=d.id, name=d.name, filename=d.filename, row_count=d.row_count, size_bytes=d.size_bytes,
                      is_restricted=d.is_restricted, columns=json.loads(d.columns_json or "[]"), created_at=d.created_at)


async def _dataset(dataset_id: str, user: User, db: AsyncSession) -> Dataset:
    q = select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == user.tenant_id)
    d = (await db.execute(q)).scalar_one_or_none()
    if d is None or (d.is_restricted and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return d


def _audit(db: AsyncSession, user: User, text: str) -> None:
    db.add(AuditLog(tenant_id=user.tenant_id, actor=(user.email or user.id)[:64], event=text[:500], department="data"))


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def upload_dataset(file: UploadFile = File(...), name: str = Form(default=""), admin: User = Depends(require_admin),
                         db: AsyncSession = Depends(get_db)) -> DatasetOut:
    data = await file.read(ds_svc.MAX_BYTES + 1)
    try:
        headers, rows = ds_svc.parse_upload(file.filename or "", data)
    except ds_svc.DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    q = select(Dataset.id).where(Dataset.tenant_id == admin.tenant_id)
    if len((await db.execute(q)).scalars().all()) >= MAX_DATASETS:
        raise HTTPException(status_code=409, detail=f"Dataset limit reached ({MAX_DATASETS}). Delete one first.")
    cols = ds_svc.infer_columns(headers, rows)
    title = (name.strip() or (file.filename or "dataset").rsplit(".", 1)[0])[:120]
    d = Dataset(tenant_id=admin.tenant_id, name=title, filename=(file.filename or "")[:255],
                content_csv=ds_svc.to_csv_text(headers, rows), columns_json=json.dumps(cols),
                row_count=len(rows), size_bytes=len(data), created_by=admin.id)
    db.add(d)
    _audit(db, admin, f"uploaded dataset '{title}' ({len(rows)} rows)")
    await db.commit()
    await db.refresh(d)
    return _dataset_out(d)


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[DatasetOut]:
    q = select(Dataset).where(Dataset.tenant_id == user.tenant_id).order_by(Dataset.created_at.desc())
    items = (await db.execute(q)).scalars().all()
    return [_dataset_out(d) for d in items if is_admin_user(user) or not d.is_restricted]


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(dataset_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> DatasetDetail:
    d = await _dataset(dataset_id, user, db)
    cols = json.loads(d.columns_json or "[]")
    pv = eng.run({"op": "preview", "limit": 10}, cols, d.content_csv, d.name)
    return DatasetDetail(**_dataset_out(d).model_dump(), preview=pv["rows"])


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def restrict_dataset(dataset_id: str, body: RestrictBody, admin: User = Depends(require_admin),
                           db: AsyncSession = Depends(get_db)) -> DatasetOut:
    d = await _dataset(dataset_id, admin, db)
    d.is_restricted = body.is_restricted
    q = select(AnalysisReport).where(AnalysisReport.tenant_id == admin.tenant_id, AnalysisReport.dataset_id == d.id)
    for r in (await db.execute(q)).scalars().all():
        r.is_restricted = body.is_restricted
    _audit(db, admin, f"set dataset '{d.name}' restricted={body.is_restricted}")
    await db.commit()
    return _dataset_out(d)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> Response:
    d = await _dataset(dataset_id, admin, db)
    q = select(AnalysisReport).where(AnalysisReport.tenant_id == admin.tenant_id, AnalysisReport.dataset_id == d.id)
    for r in (await db.execute(q)).scalars().all():          # keep the reports; unlink explicitly (SQLite ignores FK actions)
        r.dataset_id = None
    _audit(db, admin, f"deleted dataset '{d.name}'")
    await db.delete(d)
    await db.commit()
    return Response(status_code=204)


@router.post("/datasets/{dataset_id}/analyze", response_model=AnalysisOut)
async def analyze(dataset_id: str, body: AnalyzeBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AnalysisOut:
    d = await _dataset(dataset_id, user, db)
    cols = json.loads(d.columns_json or "[]")
    question = (body.question or "").strip()
    try:
        if body.spec is not None:
            spec = body.spec
        elif question:
            validate_user_prompt(question)
            spec = await svc.plan_spec(question, cols)
        else:
            raise HTTPException(status_code=422, detail="Provide a question or an analysis spec.")
        result = svc.run_on_dataset(spec, d)
    except eng.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    text, source = await svc.narrate(result, question or "Analysis")
    return AnalysisOut(**result, narrative=text, narrative_source=source)


def _report_out(r: AnalysisReport) -> ReportOut:
    return ReportOut(id=r.id, dataset_id=r.dataset_id, dataset_name=r.dataset_name, title=r.title, question=r.question,
                     result=json.loads(r.result_json or "{}"), narrative=r.narrative, narrative_source=r.narrative_source,
                     is_restricted=r.is_restricted, created_by=r.created_by, created_at=r.created_at)


async def _report(report_id: str, user: User, db: AsyncSession) -> AnalysisReport:
    q = select(AnalysisReport).where(AnalysisReport.id == report_id, AnalysisReport.tenant_id == user.tenant_id)
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None or (r.is_restricted and not is_admin_user(user)):
        raise HTTPException(status_code=404, detail="Report not found")
    return r


@router.post("/analysis-reports", response_model=ReportOut, status_code=201)
async def save_report(body: ReportBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ReportOut:
    d = await _dataset(body.dataset_id, user, db)
    q = select(AnalysisReport.id).where(AnalysisReport.tenant_id == user.tenant_id)
    if len((await db.execute(q)).scalars().all()) >= MAX_REPORTS:
        raise HTTPException(status_code=409, detail="Saved report limit reached. Delete old reports first.")
    try:
        result = svc.run_on_dataset(body.spec, d)                 # recomputed here; the client's numbers are never stored
    except eng.SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    text, source = await svc.narrate(result, body.question or body.title)
    r = AnalysisReport(tenant_id=user.tenant_id, dataset_id=d.id, dataset_name=d.name, title=body.title.strip()[:200],
                       question=body.question.strip(), spec_json=json.dumps(result["spec"]),
                       result_json=json.dumps(result, default=str), narrative=text, narrative_source=source,
                       is_restricted=d.is_restricted, created_by=user.id)
    db.add(r)
    _audit(db, user, f"saved analysis report '{r.title}'")
    await db.commit()
    await db.refresh(r)
    return _report_out(r)


@router.get("/analysis-reports", response_model=list[ReportOut])
async def list_reports(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[ReportOut]:
    q = select(AnalysisReport).where(AnalysisReport.tenant_id == user.tenant_id).order_by(AnalysisReport.created_at.desc()).limit(200)
    return [_report_out(r) for r in (await db.execute(q)).scalars().all() if is_admin_user(user) or not r.is_restricted]


@router.get("/analysis-reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ReportOut:
    return _report_out(await _report(report_id, user, db))


@router.get("/analysis-reports/{report_id}/export.csv")
async def export_report(report_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    r = await _report(report_id, user, db)
    res = json.loads(r.result_json or "{}")
    body = ds_svc.export_csv(res.get("columns", []), res.get("rows", []))
    return Response(content=body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="analysis-report.csv"'})


@router.delete("/analysis-reports/{report_id}", status_code=204)
async def delete_report(report_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    r = await _report(report_id, user, db)
    if r.created_by != user.id and not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Only the author or an administrator can delete a report")
    await db.delete(r)
    await db.commit()
    return Response(status_code=204)
