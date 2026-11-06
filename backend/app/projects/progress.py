"""Evidence-based project progress and the Project Evaluation Agent.

Calculation (documented in the README and shown in the UI):
  weight(task) = estimated_hours × priority factor (Critical 1.5, High 1.2, Medium 1.0, Low 0.8)
  verified %   = weight of tasks whose deliverable a manager accepted ÷ total weight × 100
  in progress  = weight of started or in-review tasks (counted fully in this band, never as verified)
  blocked      = weight of tasks that are flagged, disrupted, or waiting on dependencies
  pending      = everything else
Employee-reported percentages and manager-reported percentages are shown beside verified progress
and never added to it.
"""
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException

from .audit import utcnow
from .store import STORE

PRIORITY_WEIGHT = {"Critical": 1.5, "High": 1.2, "Medium": 1.0, "Low": 0.8}
BLOCKED = {"BLOCKED_BY_DEPENDENCY", "AT_RISK_DISRUPTED", "REALLOCATION_PROPOSED"}
ACTIVE = {"IN_PROGRESS", "DELIVERABLE_IN_REVIEW"}
DONE = "COMPLETED_AND_AUDITED"
METHOD = ("Weighted by effort × priority. Verified = deliverables accepted by a manager. Reported percentages are never counted as verified.")


def _weight(t) -> float:
    return t.estimated_hours * PRIORITY_WEIGHT.get(t.priority, 1.0)


def task_due(project, task) -> Optional[date]:
    if not project.start_date:
        return None
    return date.fromisoformat(project.start_date) + timedelta(days=task.deadline_days)


def bucket(t) -> str:
    if t.status == DONE:
        return "verified"
    if t.blocked or t.status in BLOCKED:
        return "blocked"
    if t.status in ACTIVE:
        return "in_progress"
    return "pending"


def project_progress(project_id: str) -> Dict:
    project = STORE.project(project_id)
    tasks = [t for t in STORE.tasks if t.project_id == project_id]
    total = sum(_weight(t) for t in tasks)
    bands = {"verified": 0.0, "in_progress": 0.0, "blocked": 0.0, "pending": 0.0}
    for t in tasks:
        bands[bucket(t)] += _weight(t)
    pct = {k: round(v / total * 100, 1) if total else 0.0 for k, v in bands.items()}
    today = date.today()
    start = date.fromisoformat(project.start_date) if project.start_date else today
    deadline = start + timedelta(days=project.deadline_days)
    days_remaining = (deadline - today).days
    open_tasks = [t for t in tasks if t.status != DONE]
    overdue = [t for t in open_tasks if (task_due(project, t) or today) < today]
    critical_blockers = [t for t in tasks if bucket(t) == "blocked" and t.priority == "Critical"]
    expected = min(100.0, max(0.0, (today - start).days / max(project.deadline_days, 1) * 100))
    if not tasks:
        health = "Not planned"
    elif pct["verified"] >= 100:
        health = "Complete"
    elif days_remaining < 0 or critical_blockers and overdue:
        health = "Off track"
    elif critical_blockers or overdue or pct["verified"] < expected - 25:
        health = "At risk"
    else:
        health = "On track"
    milestones: Dict[str, List] = {}
    for t in sorted(tasks, key=lambda x: x.deadline_days):
        milestones.setdefault(t.milestone or "Delivery", []).append(t)
    current = next((name for name, ts in milestones.items() if any(x.status != DONE for x in ts)), None)
    reported_employee = round(sum(_weight(t) * t.progress_pct for t in tasks) / total, 1) if total else 0.0
    _m = STORE.one("progress_updates", project_id=project_id)
    manager = {k: _m[k] for k in ("reported_pct", "note", "reported_by", "created_at")} if _m else None
    activity_times = [a["at"] for t in tasks for a in t.activity]
    last_snapshot = STORE.one("progress_snapshots", project_id=project_id)
    return {
        "project_id": project.id, "name": project.name, "status": project.status, "priority": project.priority,
        "bands_pct": pct, "completion_pct": pct["verified"], "method": METHOD,
        "reported_by_employees_pct": reported_employee, "reported_by_manager": manager,
        "start_date": start.isoformat(), "deadline": deadline.isoformat(), "days_remaining": days_remaining, "expected_pct_by_schedule": round(expected, 1),
        "health": health, "current_milestone": current, "milestones": [{"name": n, "done": sum(1 for x in ts if x.status == DONE), "total": len(ts)} for n, ts in milestones.items()],
        "open_tasks": len(open_tasks), "total_tasks": len(tasks), "overdue_tasks": [t.id for t in overdue],
        "critical_blockers": [{"task_id": t.id, "title": t.title, "reason": t.blocked_reason or t.status} for t in critical_blockers],
        "last_update": max(activity_times + ([last_snapshot["created_at"]] if last_snapshot else []), default=None),
        "history": [{k: h[k] for k in ("verified_pct", "in_progress_pct", "blocked_pct", "pending_pct", "created_at")}
                    for h in STORE.rows("progress_snapshots", project_id=project_id)[-30:]],
    }


def snapshot_all() -> None:
    """Called after mutating requests; stores a history point only when a project's bands changed."""
    for project in STORE.projects:
        if project.status == "Archived":
            continue
        tasks = [t for t in STORE.tasks if t.project_id == project.id]
        total = sum(_weight(t) for t in tasks)
        if not total:
            continue
        bands = {"verified": 0.0, "in_progress": 0.0, "blocked": 0.0, "pending": 0.0}
        for t in tasks:
            bands[bucket(t)] += _weight(t)
        current = tuple(round(bands[k] / total * 100, 1) for k in ("verified", "in_progress", "blocked", "pending"))
        last = STORE.one("progress_snapshots", project_id=project.id)
        if last and (last["verified_pct"], last["in_progress_pct"], last["blocked_pct"], last["pending_pct"]) == current:
            continue
        STORE.add("progress_snapshots", {"project_id": project.id, "verified_pct": current[0], "in_progress_pct": current[1],
                                         "blocked_pct": current[2], "pending_pct": current[3]})


def report_progress(project_id: str, pct: float, note: str, actor: str) -> Dict:
    STORE.project(project_id)
    STORE.add("progress_updates", {"id": STORE.next_id("PRG"), "project_id": project_id, "reported_pct": pct, "note": note,
                                   "reported_by": actor})
    with STORE.lock:
        STORE.ledger.record(actor, "MANAGER_PROGRESS_REPORTED", project_id, {"reported_pct": pct})
    return project_progress(project_id)


def evaluate_project(project_id: str) -> Dict:
    """Project Evaluation Agent: compares reported progress, verified evidence and the approved requirements."""
    import json
    progress = project_progress(project_id)
    project = STORE.project(project_id)
    tasks = [t for t in STORE.tasks if t.project_id == project_id]
    findings: List[Dict] = []
    limitations: List[str] = []
    actions: List[str] = []

    def finding(level: str, title: str, detail: str, action: Optional[str] = None) -> None:
        findings.append({"level": level, "title": title, "detail": detail})
        if action:
            actions.append(action)

    manager = progress["reported_by_manager"]
    if manager:
        gap = round(manager["reported_pct"] - progress["completion_pct"], 1)
        if gap > 10:
            finding("High", "Reported progress exceeds verified evidence",
                    f"{manager['reported_by']} reported {manager['reported_pct']}% but accepted deliverables support {progress['completion_pct']}% (gap {gap} points).",
                    "Review in-progress deliverables and accept those that meet their criteria, or correct the reported figure.")
    else:
        limitations.append("No manager progress report has been recorded, so reported and verified progress cannot be compared.")
    if progress["reported_by_employees_pct"] - progress["completion_pct"] > 25:
        finding("Medium", "Work reported but not verified", f"Employees report {progress['reported_by_employees_pct']}% against {progress['completion_pct']}% verified.",
                "Ask owners to submit deliverables for review.")
    for b in progress["critical_blockers"]:
        finding("Critical", f"Critical blocker on {b['task_id']}", f"{b['title']}: {b['reason'].replace('_', ' ').lower()}", f"Resolve the blocker on {b['task_id']} or reassign it.")
    if progress["overdue_tasks"]:
        finding("High", "Overdue tasks", ", ".join(progress["overdue_tasks"]), "Re-plan overdue tasks or adjust their deadlines with approval.")
    unassigned = [t.id for t in tasks if not t.assigned_to and t.status != DONE]
    if unassigned:
        finding("Medium", "Tasks without an owner", ", ".join(unassigned), "Run allocation for unassigned tasks.")
    no_criteria = [t.id for t in tasks if not t.acceptance_criteria]
    if no_criteria:
        finding("Medium", "Tasks without acceptance criteria", ", ".join(no_criteria), "Add measurable acceptance criteria so completion can be verified.")

    spec_row = STORE.one("specs", project_id=project_id)
    coverage = None
    if spec_row:
        analysis = spec_row["analysis"]
        requirements = [i["text"] for i in analysis.get("functional_requirements", [])]
        haystack = " ".join(f"{t.title} {t.description} {' '.join(t.acceptance_criteria)}" for t in tasks).lower()
        uncovered = [r for r in requirements if len(set(re.findall(r"[a-z]{5,}", r.lower())) & set(re.findall(r"[a-z]{5,}", haystack))) < 2]
        coverage = {"requirements": len(requirements), "uncovered": uncovered[:15]}
        if uncovered:
            finding("Medium", f"{len(uncovered)} requirement(s) with no matching task", "; ".join(u[:90] for u in uncovered[:3]), "Add tasks or confirm these requirements are out of scope.")
        if spec_row["approved_at"]:
            later = [d for d in STORE.rows("documents_index", project_id=project_id, is_current=True)
                     if d["uploaded_at"] > spec_row["approved_at"]]
            if later:
                finding("High", "Possible scope change", f"Documents added after the specification was approved: {', '.join(d['filename'] for d in later)}.", "Re-analyse the project and compare the specification.")
    else:
        limitations.append("No document analysis exists for this project, so requirement coverage cannot be assessed.")
    if not tasks:
        limitations.append("The project has no tasks yet.")
    if progress["completion_pct"] == 0 and tasks:
        limitations.append("No deliverable has been accepted yet, so verified progress is 0% regardless of work in flight.")
    return {"agent": "Project Evaluation Agent", "project_id": project.id, "project": project.name, "health": progress["health"], "progress": progress,
            "findings": findings, "corrective_actions": list(dict.fromkeys(actions)), "requirement_coverage": coverage, "limitations": limitations, "evaluated_at": utcnow()}


def assert_project_access(user: Dict, project_id: str) -> None:
    """Admins see all projects in the organization; staff only projects where they own a task."""
    project = STORE.project(project_id)
    if user["role"] == "ADMIN" or user["sub"] in project.manager_usernames:
        return
    emp = user.get("emp")
    if not emp or not any(t.project_id == project.id and t.assigned_to == emp for t in STORE.tasks):
        raise HTTPException(403, "You are not assigned to this project")


def assert_can_manage(user: Dict, project_id: str) -> None:
    """Administrators, and managers named on this project. Being a manager somewhere else gives nothing here."""
    project = STORE.project(project_id)
    if user["role"] != "ADMIN" and not (user.get("org_role") == "MANAGER" and user["sub"] in project.manager_usernames):
        raise HTTPException(403, "Only an administrator or this project's manager can do this")


def visible_projects(user: Dict) -> List:
    live = [p for p in STORE.projects if p.status != "Archived"]
    if user["role"] == "ADMIN":
        return live
    mine = {t.project_id for t in STORE.tasks if t.assigned_to == user.get("emp")} if user.get("emp") else set()
    return [p for p in live if p.id in mine or user["sub"] in p.manager_usernames]


STAGES = {"draft": "Draft", "under_evaluation": "Under AI evaluation", "awaiting_clarification": "Awaiting clarification", "awaiting_approval": "Awaiting approval", "approved": "Approved",
          "awaiting_allocation": "Awaiting team allocation", "in_progress": "In progress", "blocked": "Blocked", "completed": "Completed", "cancelled": "Cancelled"}


def project_stage(project) -> str:
    """Worked out from the records themselves, so it cannot disagree with them. A team being allocated never reads as work being done."""
    if project.status == "Archived":
        return "cancelled"
    if project.status == "Completed":
        return "completed"
    tasks = [t for t in STORE.tasks if t.project_id == project.id]
    if tasks:
        if all(t.status == DONE for t in tasks):
            return "completed"
        if any(t.status in ACTIVE for t in tasks):
            return "blocked" if any(t.blocked or t.status in BLOCKED for t in tasks) and not any(t.status in ACTIVE and not t.blocked for t in tasks) else "in_progress"
        if any(t.blocked or t.status in BLOCKED - {"BLOCKED_BY_DEPENDENCY"} for t in tasks):
            return "blocked"
        if any(t.status == "PENDING_HITL_APPROVAL" for t in tasks):
            return "awaiting_approval"
        if any(not t.assigned_to and t.status != DONE for t in tasks):
            return "awaiting_allocation"
        return "approved"
    if STORE.rows("clarifications", project_id=project.id, status="open"):
        return "awaiting_clarification"
    spec = STORE.one("specs", project_id=project.id)
    plan = STORE.one("plans", project_id=project.id)
    if plan or spec:
        return "awaiting_approval"
    if STORE.rows("documents_index", project_id=project.id, is_current=True):
        return "under_evaluation"
    return "draft"


def overview(user: Dict) -> Dict:
    """Project count and real teams. A project without assigned people has an empty team, which is a normal state."""
    names = {e.id: e for e in STORE.employees}
    projects = []
    for p in visible_projects(user):
        owners = sorted({t.assigned_to for t in STORE.tasks if t.project_id == p.id and t.assigned_to and t.assigned_to in names})
        stage = project_stage(p)
        projects.append({"project_id": p.id, "name": p.name, "stage": stage, "stage_label": STAGES[stage], "priority": p.priority,
                         "team": [{"employee_id": e, "name": names[e].name, "designation": names[e].designation} for e in owners]})
    counts = {k: sum(1 for x in projects if x["stage"] == k) for k in STAGES}
    return {"total": len(projects), "stages": [{"key": k, "label": v, "count": counts[k]} for k, v in STAGES.items() if counts[k]], "projects": projects}


def record_transitions(actor: str) -> None:
    """Called after mutating requests: keeps a history of each project's stage with who caused the change."""
    for project in STORE.projects:
        stage = project_stage(project)
        last = STORE.one("transitions", project_id=project.id)
        if not last or last["to_stage"] != stage:
            STORE.add("transitions", {"project_id": project.id, "from_stage": last["to_stage"] if last else None, "to_stage": stage,
                                      "actor": actor})
