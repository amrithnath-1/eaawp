"""Operations shared by REST routes and the AI assistant, so both go through the same validation and audit path."""
from datetime import date
from typing import Dict, List, Optional

from fastapi import HTTPException

from . import engine
from .agents import RiskPredictionAgent, TaskAllocationAgent, _decision
from .audit import utcnow
from .models import (ApprovalRecord, AvailabilitySchedule, Employee, Project, Task, TaskAssignment)
from .store import STORE

allocator = TaskAllocationAgent()
risk = RiskPredictionAgent()


def username_of(employee_id: Optional[str]) -> Optional[str]:
    """EAAWP: people are reached by their roster record (linked to their EAAWP account by email)."""
    return employee_id


def _log(task: Task, actor: str, text: str) -> None:
    task.activity.append({"at": utcnow(), "actor": actor, "text": text})


def run_allocation(actor: str, project_id: Optional[str] = None) -> Dict:
    result = allocator.allocate_all(actor, project_id)
    pending = 0
    for a in result["allocations"]:
        task = next((t for t in STORE.tasks if t.id == a["task_id"]), None)
        if task and task.assigned_to:
            _log(task, actor, f"Allocated to {a['recommended']['employee_name']} (score {a['recommended']['suitability_score']}), status {task.status}")
            if task.status == "ASSIGNED":
                STORE.notify("assignment", f"New task: {task.id}", task.title, audience_employee=task.assigned_to)
        pending += 1 if a["status"] == "PENDING_HITL_APPROVAL" else 0
    if pending:
        STORE.notify("approval", f"{pending} allocation(s) need approval", "Critical tasks or assignments above 85% load wait for a manager.", audience_role="ADMIN")
    return result


def decide_approval_notifications(result: Dict) -> None:
    apr = result["approval"]
    if apr["status"] == "APPROVED" and apr.get("recommended_new_owner_id"):
        STORE.notify("assignment", f"Task assigned: {apr['task_id']}", apr["task_title"], audience_employee=apr["recommended_new_owner_id"])


def assign_task(task_id: str, employee_id: str, reason: str, actor: str) -> Dict:
    """Manual assignment still passes the deterministic hard constraints."""
    with STORE.lock:
        task = STORE.task(task_id)
        if task.status == "COMPLETED_AND_AUDITED":
            raise HTTPException(409, "Completed tasks cannot be reassigned")
        if task.assigned_to == employee_id:
            raise HTTPException(409, "The task is already assigned to this employee")
        emp = STORE.employee(employee_id)
        check = engine.score_candidate_for_task(emp, task, STORE.weights)
        if not check["eligible"]:
            raise HTTPException(409, "This assignment breaks a hard constraint: " + "; ".join(check["hard_violations"]))
        prev = STORE.find_employee(task.assigned_to)
        if prev:
            prev.committed_hrs = max(0.0, prev.committed_hrs - task.estimated_hours)
        for a in STORE.assignments:
            if a.task_id == task.id and a.status in ("ACTIVE", "PENDING_HITL_APPROVAL"):
                a.status = "RELEASED"
        for a in STORE.approvals:     # an explicit manager decision closes any open proposal for this task
            if a.task_id == task.id and a.status == "PENDING":
                a.status, a.manager_comments, a.decided_by, a.decided_at = "REJECTED", "Superseded by manual assignment", actor, utcnow()
        emp.committed_hrs += task.estimated_hours
        task.assigned_to, task.status = emp.id, "ASSIGNED"
        STORE.assignments.append(TaskAssignment(id=STORE.next_id("ASG"), task_id=task.id, employee_id=emp.id, suitability_score=check["suitability_score"],
                                                factor_breakdown=check["factor_breakdown"], explanation_rationale=f"Assigned by {actor}: {reason}",
                                                tradeoffs_flagged=check["warnings"], status="ACTIVE"))
        _log(task, actor, f"Assigned to {emp.name}: {reason}")
        STORE.ledger.record(actor, "TASK_ASSIGNED_MANUALLY", task.id, {"from": prev.id if prev else None, "to": emp.id, "reason": reason, "score": check["suitability_score"]})
        verified = STORE.task(task_id).assigned_to == emp.id
    STORE.notify("assignment", f"Task assigned: {task.id}", task.title, audience_employee=emp.id)
    return {"status": "ASSIGNED", "verified": verified, "task": task.model_dump(), "candidate": check}


def propose_reassignment(task_id: str, actor: str, reason: str) -> Dict:
    """Creates a human approval record with the best alternative owner. Nothing moves until it is approved."""
    with STORE.lock:
        task = STORE.task(task_id)
        if any(a.task_id == task.id and a.status == "PENDING" and a.kind == "REALLOCATION" for a in STORE.approvals):
            raise HTTPException(409, f"{task.id} already has an open reassignment proposal")
        cands = engine.rank_candidates(STORE.employees, task, STORE.weights, exclude=task.assigned_to)
        best = cands[0] if cands and cands[0]["eligible"] else None
        prev = STORE.find_employee(task.assigned_to)
        text = (f"{reason}. Recommend {best['employee_name']} (Suitability {best['suitability_score']}/100, post-load {best['utilization_after_pct']}%)." if best
                else f"{reason}. No eligible internal candidate: {'; '.join(cands[0]['hard_violations']) if cands else 'no candidates'}.")
        dec = _decision("Agent 7 (Coordination Supervisor)", f"REASSIGN {task.id}", cands, f"REASSIGN {task.id}", "Medium", True)
        apr = ApprovalRecord(approval_id=STORE.next_id("APR"), decision_id=dec.id, kind="REALLOCATION", task_id=task.id, task_title=task.title, priority=task.priority,
                             previous_owner=prev.name if prev else None, previous_owner_id=prev.id if prev else None,
                             recommended_new_owner_id=best["employee_id"] if best else None, recommended_new_owner_name=best["employee_name"] if best else None,
                             suitability_score=best["suitability_score"] if best else 0.0, post_utilization_pct=best["utilization_after_pct"] if best else 0.0,
                             explanation=text, shortlist=cands[:4], created_at=utcnow())
        STORE.approvals.append(apr)
        if best:
            task.status = "REALLOCATION_PROPOSED"
        _log(task, actor, f"Reassignment proposed: {reason}")
        STORE.ledger.record(actor, "REASSIGNMENT_PROPOSED", task.id, {"approval": apr.approval_id, "to": apr.recommended_new_owner_id})
    STORE.notify("approval", f"Reassignment proposed: {task.id}", text[:160], audience_role="ADMIN")
    return apr.model_dump()


def report_leave(employee_id: str, days: int, reason: str, actor: str) -> Dict:
    result = risk.disruption(employee_id, "On Leave", days, reason, actor)
    if result["proposals_created"]:
        STORE.notify("approval", f"{result['disrupted_employee']} unavailable", f"{len(result['proposals_created'])} reallocation proposal(s) need approval.", audience_role="ADMIN")
    return result


# ------------------------------------------------------------------ projects & tasks
def create_draft_project(name: str, objective: str, priority: str, deadline_days: int, actor: str) -> Dict:
    with STORE.lock:
        if any(p.name.lower() == name.lower() and p.status != "Archived" for p in STORE.projects):
            raise HTTPException(409, f"A project named '{name}' already exists")
        project = Project(id=STORE.next_id("PRJ"), name=name, business_objective=objective, priority=priority, deadline_days=deadline_days,
                          status="Draft", created_by=actor, start_date=date.today().isoformat())
        STORE.projects.append(project)
        STORE.ledger.record(actor, "PROJECT_CREATED", project.id, {"name": name})
    return project.model_dump()


def update_project(project_id: str, changes: Dict, actor: str) -> Dict:
    with STORE.lock:
        project = STORE.project(project_id)
        before = {k: getattr(project, "business_objective" if k == "objective" else k) for k in changes}
        for k, v in changes.items():
            setattr(project, "business_objective" if k == "objective" else k, v)
        STORE.ledger.record(actor, "PROJECT_UPDATED", project_id, {"before": before, "after": changes})
    return project.model_dump()


def create_task(project_id: str, data: Dict, actor: str) -> Dict:
    with STORE.lock:
        STORE.project(project_id)
        project_ids = {t.id for t in STORE.tasks if t.project_id == project_id}
        unknown = [d for d in data["dependencies"] if d not in project_ids]
        if unknown:
            raise HTTPException(422, f"Unknown dependencies in this project: {', '.join(unknown)}")
        task = Task(id=STORE.next_id("TSK"), project_id=project_id, deliverable_criteria="; ".join(data["deliverables"]) or "Accepted deliverable", **data)
        _log(task, actor, "Task created manually")
        STORE.tasks.append(task)
        STORE.ledger.record(actor, "TASK_CREATED", task.id, {"project": project_id})
    return task.model_dump()


def update_task(task_id: str, changes: Dict, actor: str) -> Dict:
    with STORE.lock:
        task = STORE.task(task_id)
        before = {k: getattr(task, k) for k in changes}
        new_hours = changes.get("estimated_hours")
        owner = STORE.find_employee(task.assigned_to)
        if new_hours is not None and owner:
            owner.committed_hrs = max(0.0, owner.committed_hrs + new_hours - task.estimated_hours)
        for k, v in changes.items():
            setattr(task, k, v)
        if "deadline_days" in changes:
            _log(task, actor, f"Deadline moved from day {before['deadline_days']} to day {changes['deadline_days']}")
        if "blocked" in changes:
            _log(task, actor, f"{'Blocked: ' + (task.blocked_reason or 'no reason given') if task.blocked else 'Unblocked'}")
        STORE.ledger.record(actor, "TASK_UPDATED", task.id, {"before": before, "after": changes})
    return task.model_dump()


def delete_task(task_id: str, actor: str) -> Dict:
    with STORE.lock:
        task = STORE.task(task_id)
        dependents = [t.id for t in STORE.tasks if task_id in t.dependencies]
        if dependents:
            raise HTTPException(409, f"Other tasks depend on this one: {', '.join(dependents)}")
        if task.status in ("IN_PROGRESS", "DELIVERABLE_IN_REVIEW", "COMPLETED_AND_AUDITED"):
            raise HTTPException(409, f"A task that is {task.status.replace('_', ' ').lower()} cannot be deleted")
        owner = STORE.find_employee(task.assigned_to)
        if owner:
            owner.committed_hrs = max(0.0, owner.committed_hrs - task.estimated_hours)
        for a in STORE.assignments:
            if a.task_id == task_id and a.status in ("ACTIVE", "PENDING_HITL_APPROVAL"):
                a.status = "RELEASED"
        for a in STORE.approvals:
            if a.task_id == task_id and a.status == "PENDING":
                a.status, a.manager_comments, a.decided_by, a.decided_at = "REJECTED", "Task deleted", actor, utcnow()
        STORE.tasks.remove(task)
        STORE.ledger.record(actor, "TASK_DELETED", task_id, {"title": task.title})
    return {"status": "DELETED", "task_id": task_id}


def request_rework(task_id: str, reason: str, actor: str) -> Dict:
    with STORE.lock:
        task = STORE.task(task_id)
        if task.status != "DELIVERABLE_IN_REVIEW":
            raise HTTPException(409, "Only deliverables in review can be sent back")
        task.status = "IN_PROGRESS"
        task.progress_pct = min(task.progress_pct, 80)
        _log(task, actor, f"Rework requested: {reason}")
        STORE.ledger.record(actor, "DELIVERABLE_REWORK_REQUESTED", task.id, {"reason": reason})
    STORE.notify("rework", f"Rework requested: {task.id}", reason, audience_employee=task.assigned_to)
    return task.model_dump()


# ------------------------------------------------------------------ employees
def create_employee(data: Dict, actor: str) -> Dict:
    """A roster record. The person signs in with their EAAWP account; the two are linked by email."""
    data.pop("password", None)
    with STORE.lock:
        if any(e.email.lower() == data["email"].lower() for e in STORE.employees):
            raise HTTPException(409, "An employee with this email already exists")
        number = max([int(e.id.split("-")[1]) for e in STORE.employees if e.id.split("-")[-1].isdigit()]
                     + [STORE.counters.get("EMP", 0)]) + 1
        STORE.counters["EMP"] = number
        emp = Employee(id=f"EMP-{number:02d}", team_role_id="ROLE-ENG", committed_hrs=0, delivery_completion_rate=0, work_quality_acceptance_rate=0,
                       deadline_reliability_rate=0, collaboration_review_score=0, learning_improvement_score=0, preferred_tasks=[], learning_goals=[],
                       sufficient_evidence=False, availability=AvailabilitySchedule(meeting_hrs_week=data["meeting_hrs"]), **data)
        STORE.employees.append(emp)
        STORE.ledger.record(actor, "EMPLOYEE_CREATED", emp.id, {"name": emp.name})
    return {"employee": engine.compute_6_scores(emp)}


def update_employee(employee_id: str, changes: Dict, actor: str) -> Dict:
    with STORE.lock:
        emp = STORE.employee(employee_id)
        before = {k: (v if k != "skills" else len(emp.skills)) for k, v in ((k, getattr(emp, k)) for k in changes)}
        for k, v in changes.items():
            setattr(emp, k, v)
        STORE.ledger.record(actor, "EMPLOYEE_UPDATED", emp.id, {"before": before, "fields": sorted(changes)})
    return engine.compute_6_scores(emp)


def deactivate_employee(employee_id: str, actor: str) -> Dict:
    """Records are retained for audit and evidence; sign-in is blocked and the person leaves allocation."""
    with STORE.lock:
        emp = STORE.employee(employee_id)
        open_tasks = [t.id for t in STORE.tasks if t.assigned_to == emp.id and t.status != "COMPLETED_AND_AUDITED"]
        if open_tasks:
            raise HTTPException(409, f"Reassign this employee's open tasks first: {', '.join(open_tasks)}")
        emp.status = "Inactive"
        STORE.ledger.record(actor, "EMPLOYEE_DEACTIVATED", emp.id, {"name": emp.name})
    return {"status": "DEACTIVATED", "employee_id": emp.id}


# ------------------------------------------------------------------ employee change requests
def create_change_request(employee_id: str, kind: str, task_id: Optional[str], details: str, actor: str) -> Dict:
    emp = STORE.employee(employee_id)
    if task_id:
        task = STORE.task(task_id)
        if task.assigned_to != employee_id:
            raise HTTPException(403, "You can only make requests about your own tasks")
    elif kind != "leave":
        raise HTTPException(422, "Choose the task this request is about")
    row = STORE.add("change_requests", {"id": STORE.next_id("REQ"), "employee_id": employee_id, "kind": kind, "task_id": task_id,
                                        "details": details, "status": "open", "resolution": None, "resolved_by": None})
    STORE.ledger.record(actor, "CHANGE_REQUESTED", employee_id, {"kind": kind, "task": task_id})
    STORE.notify("change_request", f"{emp.name}: {kind.replace('_', ' ')} request", details[:160], audience_role="ADMIN")
    return dict(row)


def list_change_requests(employee_id: Optional[str] = None) -> List[Dict]:
    rows = STORE.rows("change_requests", employee_id=employee_id) if employee_id else list(STORE.records["change_requests"])
    rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    if not employee_id:
        rows = sorted(rows, key=lambda r: r["status"] != "open")[:50]
    return [dict(r) for r in rows]


def resolve_change_request(request_id: str, approve: bool, note: str, new_deadline: Optional[int], leave_days: int, actor: str) -> Dict:
    row = STORE.one("change_requests", id=request_id)
    if not row:
        raise HTTPException(404, "Request not found")
    if row["status"] != "open":
        raise HTTPException(409, "This request has already been resolved")
    outcome = "Declined"
    if approve:
        if row["kind"] == "reassignment":
            apr = propose_reassignment(row["task_id"], actor, f"Requested by employee: {row['details'][:120]}")
            outcome = f"Proposal {apr['approval_id']} created"
        elif row["kind"] == "deadline_change":
            if not new_deadline:
                raise HTTPException(422, "Enter the new deadline day")
            update_task(row["task_id"], {"deadline_days": new_deadline}, actor)
            outcome = f"Deadline moved to day {new_deadline}"
        else:
            result = report_leave(row["employee_id"], leave_days, f"Leave request: {row['details'][:120]}", actor)
            outcome = f"Leave recorded, {len(result['proposals_created'])} proposal(s) created"
    row.update(status="approved" if approve else "declined", resolution=f"{outcome}. {note}".strip(), resolved_by=actor)
    STORE.ledger.record(actor, "CHANGE_REQUEST_RESOLVED", row["employee_id"], {"request": request_id, "approved": approve, "outcome": outcome})
    STORE.notify("change_request", f"Your {row['kind'].replace('_', ' ')} request", outcome, audience_employee=row["employee_id"])
    return dict(row)
