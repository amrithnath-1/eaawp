"""
Project Manager AI employee API (ported from Vyuham, the AF-07 team coordination and task allocation agent).

Everything lives under /api/v1/pm and needs the PROJECT_MANAGER module. Access follows Vyuham:
  administrators          the whole company's projects, team roster, approvals, budgets and audit ledger
  a project's managers    that project (named by an administrator; manage rights only on that project)
  everyone else           projects where they own a task, their own tasks, profile and requests
Allocation is deterministic (hard constraints, weighted suitability, fairness). Critical tasks and assignments above 85%
load wait for a person's approval. The AI model (Gemini through EAAWP's gateway) only reads documents and drafts; every
AI-made result is labelled, and a labelled rule-based path is used when the model is not configured.
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.db.models import User
from app.db.session import get_db
from app.projects import (budget, documents, employee_import, engine, llm, progress, rooms, services, skillreview, workflow,
                          workforce)
from app.projects.agents import (CoordinationAgent, PerformanceEvaluationAgent, ProgressMonitoringAgent, RiskPredictionAgent,
                                 TaskAllocationAgent, WorkforceIntelligenceAgent)
from app.projects.audit import utcnow
from app.projects.context import PmContext, assert_self_or_admin, pm_context, require_admin_ctx
from app.projects.models import (ChallengeResolveRequest, ChangeRequestCreate, ChangeRequestResolve, ClarificationAnswer,
                                 DecisionRequest, DisputeRequest, DisputeResolveRequest, DisruptionRequest, EmployeeCreateRequest,
                                 EmployeeUpdateRequest, IntegrationEvent, IntegrationEventRequest, ProfessionalLinkRequest,
                                 ProfileUpdateRequest, ProgressReportRequest, ProgressUpdateRequest, ProjectDraftRequest,
                                 ProjectUpdateRequest, ReworkRequest, SkillChallengeRequest, SpecUpdateRequest,
                                 TaskAssignRequest, TaskCreateRequest, TaskUpdateRequest, WeightConfig, WhatIfRequest)
from app.projects.store import STORE
from app.services.modules import require_module

router = APIRouter(prefix="/api/v1/pm", tags=["project-manager"], dependencies=[Depends(require_module("PROJECT_MANAGER"))])

coordinator = CoordinationAgent()
workforce_agent = WorkforceIntelligenceAgent()
allocator = TaskAllocationAgent()
monitor = ProgressMonitoringAgent()
evaluator = PerformanceEvaluationAgent()
risk = RiskPredictionAgent()


# ── request bodies only this router needs ──────────────────────────────────────
class ProjectManagerBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    add: bool = True


class SkillScoreBody(BaseModel):
    skill: str = Field(min_length=1, max_length=100)
    score: float
    confidence: str = "medium"
    reason: str = Field(min_length=1, max_length=1000)
    evidence: Optional[str] = Field(default=None, max_length=2000)


class SkillRequestCreate(BaseModel):
    skill: str = Field(min_length=1, max_length=100)
    kind: str
    requested_score: Optional[float] = None
    explanation: str = Field(min_length=1, max_length=2000)
    evidence: Optional[str] = Field(default=None, max_length=2000)


class SkillRequestReview(BaseModel):
    status: str
    notes: str = Field(default="", max_length=2000)
    score: Optional[float] = None
    confidence: str = "medium"


class SkillRequestResponse(BaseModel):
    explanation: str = Field(min_length=1, max_length=2000)
    evidence: Optional[str] = Field(default=None, max_length=2000)


class RoomMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MinutesBody(BaseModel):
    title: str = Field(default="Meeting minutes", max_length=160)
    text: str = Field(min_length=10, max_length=100_000)


class BudgetBody(BaseModel):
    currency: str
    total_minor: int
    labor_minor: Optional[int] = None
    non_labor_minor: int = 0
    reserve_minor: int = 0
    includes_tax: bool = False
    hard_limit: bool = False


class RateBody(BaseModel):
    employee_id: Optional[str] = None
    role_name: Optional[str] = None
    project_id: Optional[str] = None
    currency: str
    hourly_minor: int


class CostEntryBody(BaseModel):
    kind: str
    amount_minor: int
    task_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)
    hours: Optional[float] = None


class PolicyBody(BaseModel):
    delivery_risk: Optional[float] = Field(default=None, ge=0)
    schedule_risk: Optional[float] = Field(default=None, ge=0)
    imbalance: Optional[float] = Field(default=None, ge=0)
    reassignment: Optional[float] = Field(default=None, ge=0)
    min_suitability: Optional[float] = Field(default=None, ge=0, le=100)

    def overrides(self) -> Dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ApplyBody(PolicyBody):
    proposal_id: str


class ImportRecords(BaseModel):
    records: List[employee_import.ImportRecord] = Field(max_length=employee_import.MAX_RECORDS)


class ImportConfirm(ImportRecords):
    confirm: Literal[True]


class TeamImportBody(BaseModel):
    user_ids: List[str] = Field(default_factory=list, max_length=500)
    department: str = Field(default="General", max_length=60)


# ── helpers ────────────────────────────────────────────────────────────────────
def _csv(filename: str, header: List[str], rows: List[List]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([[f"'{v}" if isinstance(v, str) and v[:1] in "=+-@" else v for v in row] for row in rows])  # no spreadsheet formulas
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _sync_documents_index(c: PmContext, project_id: str) -> None:
    """The stage of a project reads the document list from the records, so keep it in step with pm_documents."""
    docs = await documents.list_documents(c.db, c.user.tenant_id, project_id)
    c.store.records["documents_index"] = [r for r in c.store.records["documents_index"] if r.get("project_id") != project_id] + [
        {"id": d["id"], "document_id": d["id"], "project_id": project_id, "filename": d["filename"], "version": d["version"],
         "uploaded_at": d["uploaded_at"], "is_current": bool(d["is_current"] and d["status"] == "indexed")} for d in docs]


def _summary(c: PmContext) -> Dict:
    evals = [engine.compute_6_scores(e) for e in STORE.employees]
    return {
        "total_employees": len(evals),
        "total_tasks": len(STORE.tasks),
        "workload_gini_index": engine.team_gini(STORE.employees),
        "overloaded_count": sum(1 for e in evals if e["workload_score"] > engine.HITL_LOAD_THRESHOLD),
        "on_leave_count": sum(1 for e in evals if e["status"] == "On Leave"),
        "team_free_hrs": round(sum(e["free_capacity_hrs"] for e in evals), 1),
        "weights": STORE.weights.model_dump(),
        "employees": evals,
        "tasks": [t.model_dump() for t in STORE.tasks],
        "projects": [p.model_dump() for p in STORE.projects],
        "pending_approvals": [a.model_dump() for a in STORE.approvals if a.status == "PENDING"],
        "decided_approvals": [a.model_dump() for a in STORE.approvals if a.status != "PENDING"][-10:],
        "assignments": [a.model_dump() for a in STORE.assignments],
        "decisions": [d.model_dump() for d in STORE.decisions[:20]],
        "recent_audits": STORE.ledger.latest(25),
        "ledger_status": STORE.ledger.verify(),
        "change_requests": services.list_change_requests(),
        "pending_skill_requests": skillreview.pending_count(),
        "weights_updated_at": next((e.timestamp for e in reversed(STORE.ledger.all()) if e.action == "UPDATED_SCORING_WEIGHTS"), None),
        "ai": llm.status(),
    }


def _assert_can_decide(c: PmContext, approval_id: str) -> None:
    if c.is_admin:
        return
    approval = next((a for a in STORE.approvals if a.approval_id == approval_id), None)
    if approval is None:
        raise HTTPException(403, "Only an administrator or this project's manager can decide")
    progress.assert_can_manage(c.u, STORE.task(approval.task_id).project_id)


Db = Depends(get_db)
Me = Depends(get_current_user)
Admin = Depends(require_admin)       # admin-only routes say so in their signature (also checked inside)


# ── who am I, status ─────────────────────────────────────────────────────────
@router.get("/me")
async def me(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        emp = STORE.find_employee(c.u["emp"])
        return {"is_admin": c.is_admin, "employee_id": c.u["emp"], "employee_name": emp.name if emp else None,
                "manages": [p.id for p in STORE.projects if user.id in p.manager_usernames], "ai": llm.status()}


@router.get("/system/status")
async def system_status(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return {"ai": llm.status(), "ledger": STORE.ledger.verify(), "retrieval": "BM25 keyword search over each project's own documents; no embeddings",
                "upload_limit_mb": documents.MAX_BYTES // (1024 * 1024)}


# ── dashboards ───────────────────────────────────────────────────────────────
@router.get("/dashboard/summary")
async def dashboard_summary(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return _summary(c)


@router.get("/team/directory")
async def team_directory(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user):
        return [{"employee_id": e.id, "name": e.name, "designation": e.designation, "department": e.department, "status": e.status}
                for e in STORE.employees]


@router.get("/me/portal")
async def my_portal(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        if not c.u["emp"]:
            return {"linked": False, "message": "Your account is not on the project team roster yet. An administrator can add you "
                                                "(Team → Add from EAAWP team) using your sign-in email.",
                    "projects": [progress.project_progress(p.id) for p in progress.visible_projects(c.u)]}
        data = evaluator.evaluate(c.u["emp"])
        by_id = {t.id: t for t in STORE.tasks}
        for t in data["tasks"]:
            t["dependency_status"] = [{"task_id": d, "status": by_id[d].status if d in by_id else "UNKNOWN"} for d in t["dependencies"]]
            asg = next((a for a in reversed(STORE.assignments) if a.task_id == t["id"] and a.employee_id == c.u["emp"]), None)
            t["why_me"] = asg.explanation_rationale if asg else None
            t["suitability_score"] = asg.suitability_score if asg else None
        gaps = workforce_agent.skill_gaps()["gaps"]
        data["growth"] = [{"skill": g["skill"], "recommendation": r["recommendation"]} for g in gaps
                          for r in g["training_recommendations"] if r["employee_id"] == c.u["emp"]]
        data["projects"] = [progress.project_progress(p.id) for p in progress.visible_projects(c.u)]
        data["change_requests"] = services.list_change_requests(c.u["emp"])
        data["linked"] = True
        return data


# ── configuration and audit ─────────────────────────────────────────────────
@router.post("/admin/weights")
async def update_weights(w: WeightConfig, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        before = STORE.weights.model_dump()
        STORE.weights = w
        STORE.ledger.record(c.actor, "UPDATED_SCORING_WEIGHTS", "ORG_CONFIG", {"before": before, "after": w.model_dump()})
        return {"status": "UPDATED", "weights": w.model_dump()}


@router.get("/audit")
async def audit(limit: int = 100, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return {"entries": STORE.ledger.latest(min(max(limit, 1), 500)), "verification": STORE.ledger.verify()}


@router.get("/audit/export.csv")
async def export_audit(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return _csv("project-audit-ledger.csv", ["id", "timestamp", "actor", "action", "entity", "sha256"],
                    [[e.id, e.timestamp, e.actor, e.action, e.entity_id, e.sha256_proof] for e in STORE.ledger.all()])


# ── projects ─────────────────────────────────────────────────────────────────
@router.get("/projects")
async def list_projects(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return [progress.project_progress(p.id) | {"objective": p.business_objective, "stage": progress.project_stage(p),
                                                   "stage_label": progress.STAGES[progress.project_stage(p)]}
                for p in progress.visible_projects(c.u)]


@router.get("/projects/overview")
async def projects_overview(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return progress.overview(c.u)


@router.post("/projects/draft")
async def create_draft_project(req: ProjectDraftRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.create_draft_project(req.name, req.objective, req.priority, req.deadline_days, c.actor)


@router.get("/projects/{project_id}")
async def project_detail(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        project = STORE.project(project_id)
        tasks = [t for t in STORE.tasks if t.project_id == project_id]
        stage = progress.project_stage(project)
        names = {e.id: e.name for e in STORE.employees}
        return {"project": project.model_dump(), "progress": progress.project_progress(project_id), "tasks": [t.model_dump() | {"owner_name": names.get(t.assigned_to)} for t in tasks],
                "critical_path": engine.critical_path(tasks) if tasks else {"path": [], "total_hours": 0},
                "stage": stage, "stage_label": progress.STAGES[stage], "can_manage": c.is_admin or user.id in project.manager_usernames}


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, req: ProjectUpdateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.update_project(project_id, req.model_dump(exclude_none=True), c.actor)


@router.post("/projects/{project_id}/managers")
async def set_project_manager(project_id: str, req: ProjectManagerBody, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        project = STORE.project(project_id)
        target = (await db.execute(select(User).where(User.id == req.user_id, User.tenant_id == user.tenant_id))).scalar_one_or_none()
        if target is None:
            raise HTTPException(404, "That person is not a member of your company")
        if req.add and target.id not in project.manager_usernames:
            project.manager_usernames.append(target.id)
        elif not req.add and target.id in project.manager_usernames:
            project.manager_usernames.remove(target.id)
        STORE.ledger.record(c.actor, "PROJECT_MANAGER_ADDED" if req.add else "PROJECT_MANAGER_REMOVED", project_id, {"user": target.name or target.email})
        return {"project_id": project_id, "managers": list(project.manager_usernames)}


@router.get("/projects/{project_id}/managers")
async def list_project_managers(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        ids = list(STORE.project(project_id).manager_usernames)
        rows = (await db.execute(select(User).where(User.tenant_id == user.tenant_id, User.id.in_(ids or [""])))).scalars().all()
        return [{"user_id": u.id, "name": u.name or u.email, "email": u.email} for u in rows]


@router.get("/projects/{project_id}/dag")
async def project_dag(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        tasks = [t for t in STORE.tasks if t.project_id == project_id]
        if not tasks:
            return {"tasks": [], "critical_path": {"path": [], "total_hours": 0}}
        return {"tasks": [t.model_dump() for t in engine.topo_sort(tasks)], "critical_path": engine.critical_path(tasks)}


@router.post("/projects/{project_id}/progress-report")
async def report_progress(project_id: str, req: ProgressReportRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, project_id)
        return progress.report_progress(project_id, req.reported_pct, req.note, c.actor)


@router.get("/projects/{project_id}/evaluation")
async def evaluate_project(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return progress.evaluate_project(project_id)


@router.get("/projects/{project_id}/transitions")
async def project_transitions(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return [{k: r.get(k) for k in ("from_stage", "to_stage", "actor", "created_at")} for r in STORE.rows("transitions", project_id=project_id)]


@router.get("/projects/{project_id}/export.csv")
async def export_project(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return _csv(f"{project_id}-tasks.csv", ["id", "title", "phase", "milestone", "priority", "status", "owner", "estimated_hours", "deadline_day", "reported_pct", "dependencies"],
                    [[t.id, t.title, t.phase, t.milestone, t.priority, t.status, (STORE.find_employee(t.assigned_to).name if STORE.find_employee(t.assigned_to) else ""),
                      t.estimated_hours, t.deadline_days, t.progress_pct, " ".join(t.dependencies)] for t in STORE.tasks if t.project_id == project_id])


# ── documents ────────────────────────────────────────────────────────────────
@router.get("/projects/{project_id}/documents")
async def list_documents(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return await documents.list_documents(db, user.tenant_id, project_id)


@router.post("/projects/{project_id}/documents")
async def upload_documents(project_id: str, files: List[UploadFile] = File(...), user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        STORE.project(project_id)
        results = []
        for f in files[:20]:
            data = await f.read(documents.MAX_BYTES + 1)
            try:
                doc = await documents.store_and_index(db, user.tenant_id, project_id, f.filename or "", data, c.actor)
            except ValueError as exc:
                results.append({"filename": f.filename, "status": "rejected", "error": str(exc)})
                continue
            if doc.get("duplicate"):
                results.append({"filename": f.filename, "status": "duplicate", "document_id": doc["id"],
                                "error": f"Identical to {doc['filename']} v{doc['version']}; not added again."})
                continue
            results.append({"filename": doc["filename"], "status": doc["status"], "document_id": doc["id"], "version": doc["version"],
                            "error": doc.get("error"), "suspicious_count": doc["suspicious_count"]})
        await _sync_documents_index(c, project_id)
        STORE.ledger.record(c.actor, "DOCUMENTS_UPLOADED", project_id, {"files": [{"name": r["filename"], "status": r["status"]} for r in results]})
        return {"results": results}


@router.get("/projects/{project_id}/documents/{document_id}/preview")
async def document_preview(project_id: str, document_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return await documents.preview(db, user.tenant_id, project_id, document_id)


@router.delete("/projects/{project_id}/documents/{document_id}")
async def delete_document(project_id: str, document_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        doc = await documents.get_document(db, user.tenant_id, project_id, document_id)
        name, version = doc.filename, doc.version
        await documents.delete_document(db, user.tenant_id, project_id, document_id)
        await _sync_documents_index(c, project_id)
        STORE.ledger.record(c.actor, "DOCUMENT_DELETED", project_id, {"filename": name, "version": version})
        return {"status": "DELETED"}


@router.get("/projects/{project_id}/documents-search")
async def search_documents(project_id: str, q: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_project_access(c.u, project_id)
        return await documents.search(db, user.tenant_id, project_id, q[:400])


# ── specification and plan ───────────────────────────────────────────────────
@router.post("/projects/{project_id}/analyze")
async def analyze_documents(project_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        chunks, truncated = await documents.project_text(db, user.tenant_id, project_id)
        return await workflow.analyze(project_id, c.actor, chunks, truncated)


@router.get("/projects/{project_id}/spec")
async def get_spec(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_can_manage(c.u, project_id)
        return workflow.get_spec(project_id)


@router.patch("/projects/{project_id}/spec")
async def update_spec(project_id: str, req: SpecUpdateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workflow.update_spec(project_id, req.summary, req.notes)


@router.post("/projects/{project_id}/spec/approve")
async def approve_spec(project_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workflow.approve_spec(project_id, c.actor)


@router.post("/projects/{project_id}/clarifications/{clarification_id}")
async def answer_clarification(project_id: str, clarification_id: str, req: ClarificationAnswer, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workflow.answer_clarification(project_id, clarification_id, req.answer, c.actor)


@router.get("/projects/{project_id}/plan")
async def get_plan(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_can_manage(c.u, project_id)
        return workflow.get_plan(project_id) or {"plan": None}


@router.post("/projects/{project_id}/plan/generate")
async def generate_plan(project_id: str, force: bool = False, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return await workflow.generate_plan(project_id, c.actor, force)


@router.put("/projects/{project_id}/plan/{plan_id}")
async def update_plan(project_id: str, plan_id: str, body: Dict, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workflow.update_plan(project_id, plan_id, body)


@router.post("/projects/{project_id}/plan/{plan_id}/approve")
async def approve_plan(project_id: str, plan_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workflow.approve_plan(project_id, plan_id, c.actor)


# ── tasks and allocation ─────────────────────────────────────────────────────
@router.post("/projects/{project_id}/tasks")
async def create_task(project_id: str, req: TaskCreateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.create_task(project_id, req.model_dump(), c.actor)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.update_task(task_id, req.model_dump(exclude_none=True), c.actor)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.delete_task(task_id, c.actor)


@router.post("/tasks/allocate-all")
async def allocate_all(project_id: Optional[str] = None, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.run_allocation(c.actor, project_id)


@router.get("/tasks/{task_id}/candidates")
async def task_candidates(task_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        task = STORE.task(task_id)
        return {"task": task.model_dump(), "candidates": engine.rank_candidates(STORE.employees, task, STORE.weights)}


@router.post("/simulate/what-if")
async def what_if(req: WhatIfRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return allocator.what_if(req.task_id, req.employee_id)


@router.post("/tasks/{task_id}/assign")
async def assign_task(task_id: str, req: TaskAssignRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.assign_task(task_id, req.employee_id, req.reason, c.actor)


@router.post("/tasks/{task_id}/progress")
async def update_progress(task_id: str, req: ProgressUpdateRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        if not c.u["emp"]:
            raise HTTPException(403, "Only the assigned team member can report progress")
        return monitor.update_progress(task_id, c.u["emp"], req.progress_pct, req.status, c.actor)


@router.post("/tasks/{task_id}/accept")
async def accept_deliverable(task_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, STORE.task(task_id).project_id)
        return monitor.accept_deliverable(task_id, c.actor)


@router.post("/tasks/{task_id}/rework")
async def request_rework(task_id: str, req: ReworkRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, STORE.task(task_id).project_id)
        return services.request_rework(task_id, req.reason, c.actor)


@router.get("/progress")
async def progress_report(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return monitor.report()


# ── disruption, risk, approvals ──────────────────────────────────────────────
@router.post("/disruptions/simulate")
async def simulate_disruption(req: DisruptionRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        result = risk.disruption(req.employee_id, req.new_status, req.leave_days, req.reason, c.actor)
        if result["proposals_created"]:
            STORE.notify("approval", f"{result['disrupted_employee']}: {req.new_status}",
                         f"{len(result['proposals_created'])} reallocation proposal(s) need approval.", audience_role="ADMIN")
        return result


@router.get("/risks")
async def risks(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return risk.scan()


@router.get("/skills/gaps")
async def skill_gaps(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return workforce_agent.skill_gaps()


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, req: DecisionRequest = DecisionRequest(), user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        _assert_can_decide(c, approval_id)
        result = coordinator.decide(approval_id, True, req.comments, c.actor)
        services.decide_approval_notifications(result)
        return result


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: str, req: DecisionRequest = DecisionRequest(), user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        _assert_can_decide(c, approval_id)
        return coordinator.decide(approval_id, False, req.comments, c.actor)


# ── team roster (employees) ──────────────────────────────────────────────────
@router.get("/employees")
async def list_employees(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return [engine.compute_6_scores(e) | {"email": e.email} for e in STORE.employees]


@router.post("/employees")
async def create_employee(req: EmployeeCreateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        if STORE.employee_by_email(req.email):
            raise HTTPException(409, "Someone on the roster already has this email")
        return services.create_employee(req.model_dump(), c.actor)


@router.get("/employees/eaawp-team")
async def eaawp_team(user: User = Admin, db: AsyncSession = Db):
    """Company members who are not on the project roster yet (so an administrator can add them in one step)."""
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        users = (await db.execute(select(User).where(User.tenant_id == user.tenant_id, User.is_active == True))).scalars().all()  # noqa: E712
        return [{"user_id": u.id, "name": u.name or u.email, "email": u.email, "role": u.role, "on_roster": bool(STORE.employee_by_email(u.email))} for u in users]


@router.post("/employees/from-team")
async def import_from_team(req: TeamImportBody, user: User = Admin, db: AsyncSession = Db):
    """Adds company members to the roster. Skills start empty and unverified: nothing about a person is invented."""
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        users = (await db.execute(select(User).where(User.tenant_id == user.tenant_id, User.id.in_(req.user_ids or [""])))).scalars().all()
        added, skipped = [], []
        for u in users:
            if STORE.employee_by_email(u.email):
                skipped.append(u.name or u.email)
                continue
            out = services.create_employee({"name": (u.name or u.email.split("@")[0])[:80], "email": u.email,
                                            "department": req.department or "General", "designation": u.role or "Team member", "manager": "",
                                            "years_exp": 0, "weekly_capacity_hrs": 40, "meeting_hrs": 0, "skills": []}, c.actor)
            added.append({"employee_id": out["employee"]["employee_id"], "name": out["employee"]["name"]})
        return {"added": added, "already_on_roster": skipped}


@router.patch("/employees/{employee_id}")
async def update_employee(employee_id: str, req: EmployeeUpdateRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.update_employee(employee_id, req.model_dump(exclude_none=True), c.actor)


@router.delete("/employees/{employee_id}")
async def deactivate_employee(employee_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.deactivate_employee(employee_id, c.actor)


@router.get("/employees/export.csv")
async def export_employees(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        rows = [engine.compute_6_scores(e) for e in STORE.employees]
        return _csv("project-team.csv", ["id", "name", "department", "designation", "status", "skill_score", "performance_score", "availability_score", "workload_score", "collaboration_score", "level"],
                    [[r["employee_id"], r["name"], r["department"], r["designation"], r["status"], r["skill_score"], r["performance_score"], r["availability_score"],
                      r["workload_score"], r["collaboration_score"], r["level"]] for r in rows])


@router.get("/employees/{employee_id}/evaluation")
async def employee_evaluation(employee_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        assert_self_or_admin(c, employee_id)
        return evaluator.evaluate(employee_id)


@router.get("/employees/{employee_id}/intelligence")
async def employee_intelligence(employee_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        assert_self_or_admin(c, employee_id)
        return {"employee": engine.compute_6_scores(STORE.employee(employee_id)), "profile": workforce.get_profile(employee_id), "skills": workforce.get_skills(employee_id),
                "resume": workforce.get_resume(employee_id), "links": workforce.list_links(employee_id), "challenges": workforce.list_challenges(employee_id),
                "completed": [t.model_dump() for t in STORE.tasks if t.assigned_to == employee_id and t.status == "COMPLETED_AND_AUDITED"]}


@router.put("/employees/{employee_id}/profile")
async def save_profile(employee_id: str, req: ProfileUpdateRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        assert_self_or_admin(c, employee_id)
        return workforce.save_profile(employee_id, req.model_dump(), c.actor)


@router.post("/employees/{employee_id}/skills/evaluate")
async def evaluate_skills(employee_id: str, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workforce.evaluate_skills(employee_id, c.actor)


@router.post("/employees/{employee_id}/skills/challenge")
async def challenge_skill(employee_id: str, req: SkillChallengeRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        assert_self_or_admin(c, employee_id)
        return workforce.challenge_skill(employee_id, req.skill, req.reason, c.actor)


@router.post("/skill-challenges/{challenge_id}/resolve")
async def resolve_challenge(challenge_id: str, req: ChallengeResolveRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return workforce.resolve_challenge(challenge_id, req.resolution, req.note, c.actor)


@router.post("/employees/{employee_id}/resume")
async def upload_resume(employee_id: str, file: UploadFile = File(...), target_text: Optional[str] = Form(None), task_id: Optional[str] = Form(None),
                        user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        assert_self_or_admin(c, employee_id)
        label = "Job description provided" if target_text else None
        if task_id:
            task = STORE.task(task_id)
            target_text, label = " ".join(task.required_skills), f"{task.id}: {task.title}"
        return await workforce.upload_resume(employee_id, file.filename or "", await file.read(documents.MAX_BYTES + 1), target_text, label, c.actor)


@router.post("/employees/{employee_id}/links")
async def save_link(employee_id: str, req: ProfessionalLinkRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        if c.u.get("emp") != employee_id:     # consent: only the person can link their own accounts
            raise HTTPException(403, "Only the team member can connect their own accounts")
        return await workforce.save_link(employee_id, req.provider, req.value, c.actor)


@router.delete("/employees/{employee_id}/links/{provider}")
async def remove_link(employee_id: str, provider: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        if c.u.get("emp") != employee_id:
            raise HTTPException(403, "Only the team member can disconnect their own accounts")
        return workforce.remove_link(employee_id, provider, c.actor)


@router.post("/employees/dispute")
async def file_dispute(req: DisputeRequest, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        emp_id = req.employee_id or c.u.get("emp")
        if not emp_id:
            raise HTTPException(400, "Choose the team member this dispute is about")
        assert_self_or_admin(c, emp_id)
        result = evaluator.file_dispute(emp_id, req.reason, c.actor)
        STORE.notify("dispute", "Evidence dispute filed", f"{STORE.employee(emp_id).name}: {req.reason[:140]}", audience_role="ADMIN")
        return result


@router.post("/employees/{employee_id}/dispute/resolve")
async def resolve_dispute(employee_id: str, req: DisputeResolveRequest, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return evaluator.resolve_dispute(employee_id, req.resolution, req.note, c.actor)


# ── bulk import ──────────────────────────────────────────────────────────────
@router.post("/employees/import/analyze")
async def analyze_employee_import(files: List[UploadFile] = File(...), user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        read = [(f.filename or "", await f.read(documents.MAX_BYTES + 1)) for f in files[:employee_import.MAX_FILES + 1]]
        return await employee_import.analyze(read, c.actor)


@router.post("/employees/import/validate")
async def validate_employee_import(req: ImportRecords, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return employee_import.validate(req.records)


@router.post("/employees/import/confirm")
async def confirm_employee_import(req: ImportConfirm, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return employee_import.confirm(req.records, c.actor)


# ── skills review ────────────────────────────────────────────────────────────
@router.get("/skills/scale")
async def skill_scale(user: User = Me, db: AsyncSession = Db):
    return {"scale": skillreview.SCALE, "confidence": skillreview.CONFIDENCE,
            "note": "A skill score says nothing about workload, availability, experience or delivery record."}


@router.post("/employees/{employee_id}/skills/score")
async def set_skill_score(employee_id: str, req: SkillScoreBody, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return skillreview.set_score(employee_id, req.skill, req.score, req.confidence, req.reason, req.evidence, c.actor)


@router.get("/employees/{employee_id}/skills/history")
async def skill_history(employee_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        assert_self_or_admin(c, employee_id)
        return skillreview.history(employee_id)


@router.post("/skill-requests")
async def submit_skill_request(req: SkillRequestCreate, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        if not c.u["emp"]:
            raise HTTPException(400, "Your account is not on the project team roster yet")
        return skillreview.submit(c.u["emp"], req.skill, req.kind, req.requested_score, req.explanation, req.evidence, c.actor)


@router.get("/skill-requests")
async def skill_requests(status: Optional[str] = None, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return skillreview.list_requests(c.u, status)


@router.post("/skill-requests/{request_id}/review")
async def review_skill_request(request_id: str, req: SkillRequestReview, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return skillreview.review(request_id, req.status, req.notes, req.score, req.confidence, c.actor)


@router.post("/skill-requests/{request_id}/respond")
async def respond_skill_request(request_id: str, req: SkillRequestResponse, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        return skillreview.respond(request_id, c.u.get("emp"), req.explanation, req.evidence, c.actor)


# ── change requests ──────────────────────────────────────────────────────────
@router.get("/change-requests")
async def change_requests(user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return services.list_change_requests(None if c.is_admin else (c.u["emp"] or "-"))


@router.post("/change-requests")
async def create_change_request(req: ChangeRequestCreate, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        if not c.u["emp"]:
            raise HTTPException(400, "Your account is not on the project team roster yet")
        return services.create_change_request(c.u["emp"], req.kind, req.task_id, req.details, c.actor)


@router.post("/change-requests/{request_id}/resolve")
async def resolve_change_request(request_id: str, req: ChangeRequestResolve, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return services.resolve_change_request(request_id, req.approve, req.note, req.new_deadline_days, req.leave_days, c.actor)


# ── evidence adapters ────────────────────────────────────────────────────────
@router.post("/integrations/events")
async def ingest_event(req: IntegrationEventRequest, user: User = Admin, db: AsyncSession = Db):
    """Authorized GitHub / Jira / Calendar evidence intake. Duplicate deliveries are ignored."""
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        key = f"{req.source_system}:{req.external_id}"
        if any(f"{e.source_system}:{e.external_id}" == key for e in STORE.integration_events):
            return {"status": "DUPLICATE_IGNORED", "key": key}
        emp = STORE.employee(req.employee_id)
        ev = IntegrationEvent(id=STORE.next_id("INT"), employee_id=emp.id, source_system=req.source_system, external_id=req.external_id,
                              pr_review_score=req.pr_review_score, defect_rate=req.defect_rate, summary=req.summary, received_at=utcnow())
        STORE.integration_events.append(ev)
        before = {"collaboration_review_score": emp.collaboration_review_score, "meeting_hrs": emp.meeting_hrs}
        if req.pr_review_score is not None:   # exponential smoothing so one event can't swing the score
            emp.collaboration_review_score = round(0.8 * emp.collaboration_review_score + 0.2 * req.pr_review_score, 1)
        if req.defect_rate is not None:
            emp.work_quality_acceptance_rate = round(0.9 * emp.work_quality_acceptance_rate + 0.1 * (100 - req.defect_rate), 1)
        if req.meeting_hrs_delta is not None:
            emp.meeting_hrs = max(0.0, emp.meeting_hrs + req.meeting_hrs_delta)
        STORE.ledger.record(f"ADAPTER_{req.source_system.upper()}", "EVIDENCE_INGESTED", emp.id,
                            {"event": ev.id, "key": key, "before": before,
                             "after": {"collaboration_review_score": emp.collaboration_review_score, "meeting_hrs": emp.meeting_hrs}})
        return {"status": "INGESTED", "event": ev.model_dump()}


# ── project rooms ────────────────────────────────────────────────────────────
@router.get("/projects/{project_id}/room")
async def room(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return rooms.room_view(c.u, project_id)


@router.get("/projects/{project_id}/room/messages")
async def room_messages(project_id: str, after: Optional[str] = None, q: Optional[str] = None, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return rooms.list_messages(c.u, project_id, after, q)


@router.post("/projects/{project_id}/room/messages")
async def post_room_message(project_id: str, req: RoomMessage, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        return rooms.post_message(c.u, project_id, req.content)


@router.post("/projects/{project_id}/room/minutes")
async def add_minutes(project_id: str, req: MinutesBody, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        return await rooms.add_minutes(c.u, project_id, req.title, req.text)


@router.post("/projects/{project_id}/room/minutes/file")
async def add_minutes_file(project_id: str, file: UploadFile = File(...), title: str = Form("Meeting minutes"), user: User = Me, db: AsyncSession = Db):
    data = await file.read(documents.MAX_BYTES + 1)
    try:
        ext = documents.validate_upload(file.filename or "", data, documents.RESUME_ALLOWED)
        text = "\n".join(t for _, t in documents.extract(ext, data))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "The minutes could not be read. Try pasting them as text.")
    async with pm_context(db, user, write=True) as c:
        return await rooms.add_minutes(c.u, project_id, title, text)


@router.post("/projects/{project_id}/room/minutes/{minutes_id}/approve")
async def approve_minutes(project_id: str, minutes_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, project_id)
        return rooms.approve_minutes(c.u, project_id, minutes_id)


@router.get("/projects/{project_id}/knowledge")
async def project_knowledge(project_id: str, q: str = "", user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        return rooms.knowledge(c.u, project_id, q[:400])


# ── budget and optimizer ─────────────────────────────────────────────────────
@router.get("/projects/{project_id}/budget")
async def get_budget(project_id: str, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        progress.assert_can_manage(c.u, project_id)
        return budget.report(project_id)


@router.put("/projects/{project_id}/budget")
async def set_budget(project_id: str, req: BudgetBody, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return budget.set_budget(project_id, req.model_dump(), c.actor)


@router.post("/projects/{project_id}/costs")
async def add_cost(project_id: str, req: CostEntryBody, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, project_id)
        return budget.add_entry(project_id, req.model_dump(), c.actor)


@router.get("/cost-rates")
async def cost_rates(user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user) as c:
        require_admin_ctx(c)
        return budget.list_rates()


@router.post("/cost-rates")
async def add_cost_rate(req: RateBody, user: User = Admin, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        require_admin_ctx(c)
        return budget.add_rate(req.model_dump(), c.actor)


@router.post("/projects/{project_id}/optimize")
async def optimize(project_id: str, req: PolicyBody = PolicyBody(), user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, project_id)
        return budget.propose(project_id, req.overrides())


@router.post("/projects/{project_id}/optimize/apply")
async def apply_optimized(project_id: str, req: ApplyBody, user: User = Me, db: AsyncSession = Db):
    async with pm_context(db, user, write=True) as c:
        progress.assert_can_manage(c.u, project_id)
        return budget.apply(project_id, req.proposal_id, c.actor, req.overrides())

