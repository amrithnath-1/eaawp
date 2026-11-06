"""
One company's Project Manager records, loaded for the duration of a request.

Vyuham kept each organization's core records in memory behind one lock and wrote a snapshot after every change. Here the
same records live in pm_state (one JSON row per company). A request opens the store with ``open_store``: the row is read
(locked FOR UPDATE on PostgreSQL), the code works on plain Python objects exactly as Vyuham's did, and ``save_store``
writes the result back. ``STORE`` resolves to the store of the request that is running, so the ported modules keep their
original shape (``STORE.task(...)``, ``STORE.ledger.record(...)``), and one company can never touch another's records.

``records`` replaces Vyuham's auxiliary SQL tables (specifications, clarifications, plans, budgets, cost rates and
entries, change requests, skill scores and reviews, resumes, progress reports and history, project rooms) with lists of
dicts kept in the same document. Notifications raised during a request are queued and delivered through EAAWP's own
notification service after the save.
"""
from __future__ import annotations

import contextvars
import json
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pm_models import PmState
from app.projects.audit import AuditLedger, utcnow
from app.projects.models import (AgentDecision, ApprovalRecord, Deliverable, Employee, IntegrationEvent, Project, Task,
                                 TaskAssignment, TeamRole, WeightConfig)

KINDS = ("specs", "clarifications", "plans", "progress_updates", "progress_snapshots", "transitions", "budgets", "cost_rates",
         "cost_entries", "change_requests", "skill_assessments", "skill_manual_scores", "skill_requests", "skill_challenges",
         "resumes", "profiles", "rooms", "room_messages", "room_minutes", "documents_index", "links", "project_decisions", "action_items")
CAPS = {"progress_snapshots": 2000, "transitions": 2000, "room_messages": 5000, "decisions": 500}


class Store:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.weights = WeightConfig()
        self.employees: List[Employee] = []
        self.tasks: List[Task] = []
        self.projects: List[Project] = []
        self.roles: List[TeamRole] = []
        self.deliverables: List[Deliverable] = []
        self.integration_events: List[IntegrationEvent] = []
        self.approvals: List[ApprovalRecord] = []
        self.decisions: List[AgentDecision] = []
        self.assignments: List[TaskAssignment] = []
        self.counters: Dict[str, int] = {}
        self.records: Dict[str, List[Dict]] = {k: [] for k in KINDS}
        self.ledger = AuditLedger()
        self.notices: List[Dict] = []          # delivered after the save
        self.version = 0
        self._digest: Optional[str] = None

    # ── (de)serialisation ───────────────────────────────────────────────────
    _MODELS = {"employees": Employee, "tasks": Task, "projects": Project, "roles": TeamRole, "deliverables": Deliverable,
               "integration_events": IntegrationEvent, "approvals": ApprovalRecord, "decisions": AgentDecision,
               "assignments": TaskAssignment}

    def dump(self) -> Dict:
        out: Dict[str, Any] = {k: [i.model_dump() for i in getattr(self, k)] for k in self._MODELS}
        out.update(weights=self.weights.model_dump(), counters=self.counters, records=self.records, audit=self.ledger.dump())
        return out

    @classmethod
    def load(cls, tenant_id: str, payload: Dict, version: int) -> "Store":
        s = cls(tenant_id)
        for k, model in cls._MODELS.items():
            setattr(s, k, [model(**x) for x in payload.get(k, [])])
        if payload.get("weights"):
            s.weights = WeightConfig(**payload["weights"])
        s.counters = dict(payload.get("counters") or {})
        recs = payload.get("records") or {}
        s.records = {k: list(recs.get(k, [])) for k in KINDS}
        s.ledger.load(payload.get("audit") or [])
        s.version = version
        return s

    def text(self) -> str:
        for k, cap in CAPS.items():
            if k in self.records and len(self.records[k]) > cap:
                self.records[k] = self.records[k][-cap:]
        if len(self.decisions) > CAPS["decisions"]:
            self.decisions = self.decisions[:CAPS["decisions"]]
        return json.dumps(self.dump(), default=str, sort_keys=True)

    # ── lookups (same behaviour as Vyuham's Store) ──────────────────────────
    @contextmanager
    def _nolock(self):
        yield

    @property
    def lock(self):
        return self._nolock()      # the database row lock serialises requests; kept so the ported code reads the same

    def next_id(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}-{self.counters[prefix]}"

    def employee(self, emp_id: str) -> Employee:
        emp = next((e for e in self.employees if e.id == emp_id), None)
        if emp is None:
            raise HTTPException(404, f"Employee {emp_id} not found")
        return emp

    def find_employee(self, emp_id: Optional[str]) -> Optional[Employee]:
        return next((e for e in self.employees if e.id == emp_id), None)

    def task(self, task_id: str) -> Task:
        t = next((t for t in self.tasks if t.id == task_id), None)
        if t is None:
            raise HTTPException(404, f"Task {task_id} not found")
        return t

    def project(self, project_id: str) -> Project:
        p = next((p for p in self.projects if p.id == project_id), None)
        if p is None:
            raise HTTPException(404, f"Project {project_id} not found")
        return p

    def employee_by_email(self, email: Optional[str]) -> Optional[Employee]:
        e = (email or "").strip().lower()
        return next((x for x in self.employees if x.email.lower() == e and x.status != "Inactive"), None) if e else None

    # ── records (former auxiliary tables) ───────────────────────────────────
    def rows(self, kind: str, **where) -> List[Dict]:
        return [r for r in self.records[kind] if all(r.get(k) == v for k, v in where.items())]

    def one(self, kind: str, **where) -> Optional[Dict]:
        found = self.rows(kind, **where)
        return found[-1] if found else None

    def add(self, kind: str, row: Dict) -> Dict:
        row = {"id": row.get("id") or f"{kind[:3].upper()}-{uuid.uuid4().hex[:10]}", "created_at": row.get("created_at") or utcnow(), **row}
        self.records[kind].append(row)
        return row

    def notify(self, category: str, title: str, message: str = "", *, audience_role: Optional[str] = None,
               audience_employee: Optional[str] = None) -> None:
        """Queued; delivered through EAAWP notifications after the request's changes are saved."""
        self.notices.append({"category": category, "title": title[:200], "message": message[:1000],
                             "admins": audience_role == "ADMIN", "employee_id": audience_employee})


_current: contextvars.ContextVar[Optional[Store]] = contextvars.ContextVar("pm_store", default=None)


class _Proxy:
    """STORE: the current request's store (raises if no store is open, so nothing can run without a tenant)."""

    def _s(self) -> Store:
        s = _current.get()
        if s is None:
            raise HTTPException(500, "Project Manager store is not open for this request")
        return s

    def __getattr__(self, name: str):
        return getattr(self._s(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._s(), name, value)


STORE: Any = _Proxy()


async def _load(db: AsyncSession, tenant_id: str, for_update: bool) -> Store:
    q = select(PmState).where(PmState.tenant_id == tenant_id)
    if for_update and db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        s = Store(tenant_id)
        s.ledger.record("SYSTEM_INIT", "PROJECT_WORKSPACE_CREATED", tenant_id, {})
        return s
    return Store.load(tenant_id, json.loads(row.state_json or "{}"), row.version)


@asynccontextmanager
async def open_store(db: AsyncSession, tenant_id: str, write: bool = False):
    """Load the company's store for this request (``write``: row-locked and saved by ``save_store``)."""
    store = await _load(db, tenant_id, write)
    store._digest = None if write else "read-only"
    token = _current.set(store)
    try:
        yield store
    finally:
        _current.reset(token)


async def save_store(db: AsyncSession, store: Store) -> bool:
    """Write the store back when it changed. Returns whether it changed."""
    text = store.text()
    row = (await db.execute(select(PmState).where(PmState.tenant_id == store.tenant_id))).scalar_one_or_none()
    if row is not None and row.state_json == text:
        return False
    if row is None:
        db.add(PmState(tenant_id=store.tenant_id, state_json=text, version=1))
    else:
        if row.version != store.version:
            raise HTTPException(409, "Someone else changed the project records at the same moment. Please try again.")
        row.state_json, row.version = text, row.version + 1
    await db.flush()
    return True
