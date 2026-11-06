"""Project budgets and cost rates. Money is integer minor units, so totals are exact. Estimated, committed and actual costs never mix."""
import hashlib
import json
from typing import Dict, List, Optional

from fastapi import HTTPException

from . import optimizer
from .audit import utcnow
from .models import ApprovalRecord, TaskAssignment
from .store import STORE

MAX_MINOR = 10 ** 15
ENTRY_KINDS = ("committed", "actual", "non_labor_estimate")
MIN_HISTORY_FOR_RANGE = 5


def _amount(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_MINOR:
        raise HTTPException(422, f"{label} must be a whole number of minor currency units between 0 and {MAX_MINOR}")
    return value


def set_budget(project_id: str, body: Dict, actor: str) -> Dict:
    STORE.project(project_id)
    currency = body["currency"].strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(422, "Use a three-letter currency code, for example INR or USD")
    total = _amount(body["total_minor"], "The total budget")
    labor = None if body.get("labor_minor") is None else _amount(body["labor_minor"], "The labor budget")
    reserve = _amount(body.get("reserve_minor") or 0, "The reserve")
    non_labor = _amount(body.get("non_labor_minor") or 0, "The non-labor estimate")
    if reserve + non_labor + (labor or 0) > total:
        raise HTTPException(422, "Labor, non-labor and reserve add up to more than the total budget")
    values = {"currency": currency, "total_minor": total, "labor_minor": labor, "non_labor_minor": non_labor, "reserve_minor": reserve,
              "includes_tax": bool(body.get("includes_tax")), "hard_limit": bool(body.get("hard_limit")), "updated_by": actor, "updated_at": utcnow()}
    row = STORE.one("budgets", project_id=project_id)
    if row:
        row.update(values)
    else:
        STORE.add("budgets", {"project_id": project_id, **values})
    STORE.ledger.record(actor, "BUDGET_SET", project_id, {"currency": currency, "total_minor": total})
    return report(project_id)


def add_rate(body: Dict, actor: str) -> Dict:
    if not (body.get("employee_id") or body.get("role_name")):
        raise HTTPException(422, "A rate applies to an employee or a role")
    if body.get("employee_id"):
        STORE.employee(body["employee_id"])
    if body.get("project_id"):
        STORE.project(body["project_id"])
    rate_id = STORE.next_id("RATE")
    STORE.add("cost_rates", {"id": rate_id, "employee_id": body.get("employee_id"), "role_name": body.get("role_name"),
                             "project_id": body.get("project_id"), "currency": body["currency"].strip().upper(),
                             "hourly_minor": _amount(body["hourly_minor"], "The hourly rate"), "approved_by": actor})
    if True:
        STORE.ledger.record(actor, "COST_RATE_ADDED", body.get("employee_id") or body.get("role_name"), {"rate": rate_id})     # the amount stays out of the audit trail
    return {"id": rate_id}


def list_rates() -> List[Dict]:
    return sorted([dict(r) for r in STORE.records["cost_rates"]], key=lambda r: (r["created_at"], r["id"]), reverse=True)


def rate_map(project_id: str, currency: Optional[str]) -> Dict[str, int]:
    """Most specific approved rate per employee: project and person, then person, then role. Stays on the server; responses show only totals."""
    rows = sorted(STORE.records["cost_rates"], key=lambda r: (r["created_at"], r["id"]))
    if currency:
        rows = [r for r in rows if r["currency"] == currency]
    rates: Dict[str, int] = {}
    for emp in STORE.employees:
        for test in (lambda r: r["employee_id"] == emp.id and r["project_id"] == project_id, lambda r: r["employee_id"] == emp.id and not r["project_id"],
                     lambda r: r["role_name"] == emp.designation and r["project_id"] == project_id, lambda r: r["role_name"] == emp.designation and not r["project_id"]):
            found = [r for r in rows if test(r)]
            if found:
                rates[emp.id] = found[-1]["hourly_minor"]
                break
    return rates


def add_entry(project_id: str, body: Dict, actor: str) -> Dict:
    STORE.project(project_id)
    if body["kind"] not in ENTRY_KINDS:
        raise HTTPException(422, f"Cost type must be one of {', '.join(ENTRY_KINDS)}")
    if body.get("task_id"):
        task = STORE.task(body["task_id"])
        if task.project_id != project_id:
            raise HTTPException(422, "That task belongs to a different project")
    budget = STORE.one("budgets", project_id=project_id)
    if not budget:
        raise HTTPException(409, "Set the project budget first")
    STORE.add("cost_entries", {"id": STORE.next_id("CST"), "project_id": project_id, "task_id": body.get("task_id"), "kind": body["kind"],
                               "amount_minor": _amount(body["amount_minor"], "The amount"), "currency": budget["currency"],
                               "note": body.get("note"), "hours": body.get("hours"), "created_by": actor})
    if True:
        STORE.ledger.record(actor, "COST_RECORDED", project_id, {"kind": body["kind"], "amount_minor": body["amount_minor"]})
    return report(project_id)


def report(project_id: str) -> Dict:
    project = STORE.project(project_id)
    budget = STORE.one("budgets", project_id=project_id)
    entries = STORE.rows("cost_entries", project_id=project_id)
    actual = sum(e["amount_minor"] for e in entries if e["kind"] == "actual")
    committed = sum(e["amount_minor"] for e in entries if e["kind"] == "committed")
    non_labor = sum(e["amount_minor"] for e in entries if e["kind"] == "non_labor_estimate") + (budget["non_labor_minor"] if budget else 0)
    rates = rate_map(project_id, budget["currency"] if budget else None)
    tasks = [t for t in STORE.tasks if t.project_id == project_id]
    planned, missing = 0, []
    for t in tasks:
        if t.assigned_to:
            if t.assigned_to in rates:
                planned += optimizer.labor_cost(t.estimated_hours, rates[t.assigned_to])
            else:
                missing.append(t.id)
    unassigned = [t.id for t in tasks if not t.assigned_to]
    estimate = planned + non_labor
    out: Dict = {"project_id": project.id, "has_budget": bool(budget), "currency": budget["currency"] if budget else None, "estimated_labor_minor": planned, "estimated_non_labor_minor": non_labor,
                 "committed_minor": committed, "actual_minor": actual, "tasks_without_rate": missing, "tasks_without_owner": unassigned,
                 "assumptions": ["Estimated labor is each assigned task's estimated hours times its owner's approved rate.", "Tasks without an owner or a rate are not in the estimate, so it can only be a lower bound while they exist."]}
    # A range needs evidence: only past estimate-versus-actual pairs on this project's completed work, and enough of them.
    pairs = [(t.estimated_hours, sum(e["hours"] or 0 for e in entries if e["task_id"] == t.id and e["kind"] == "actual")) for t in tasks]
    pairs = [(est, act) for est, act in pairs if act > 0 and est > 0]
    if len(pairs) >= MIN_HISTORY_FOR_RANGE:
        ratios = sorted(act / est for est, act in pairs)
        out["scenarios"] = {"basis": f"{len(pairs)} tasks with recorded actual hours", "optimistic_minor": round(planned * ratios[0]), "expected_minor": round(planned * ratios[len(ratios) // 2]), "conservative_minor": round(planned * ratios[-1])}
    else:
        out["scenarios"] = None
        out["assumptions"].append(f"No optimistic or conservative range is shown: that needs actual hours on at least {MIN_HISTORY_FOR_RANGE} tasks, and there are {len(pairs)}.")
    if budget:
        spent_or_held = actual + committed
        forecast = spent_or_held + max(0, estimate - spent_or_held)
        status = "over_budget" if forecast > budget["total_minor"] else "at_risk" if forecast > budget["total_minor"] - budget["reserve_minor"] else "within_budget"
        out.update(total_minor=budget["total_minor"], labor_budget_minor=budget["labor_minor"], reserve_minor=budget["reserve_minor"], includes_tax=bool(budget["includes_tax"]), hard_limit=bool(budget["hard_limit"]),
                   remaining_minor=budget["total_minor"] - spent_or_held, forecast_at_completion_minor=forecast, variance_minor=budget["total_minor"] - forecast, status=status)
    return out


def _policy() -> Dict:
    return {}


def propose(project_id: str, policy: Optional[Dict] = None) -> Dict:
    """Runs the optimizer and changes nothing. The proposal id ties a later approval to exactly this plan and these inputs."""
    STORE.project(project_id)
    budget = STORE.one("budgets", project_id=project_id)
    tasks = [t for t in STORE.tasks if t.project_id == project_id and not t.assigned_to and t.status in ("READY_FOR_ALLOCATION", "BLOCKED_BY_DEPENDENCY", "DRAFT_GENERATED")]
    rates = rate_map(project_id, budget["currency"] if budget else None)
    result = optimizer.optimize(tasks, STORE.employees, rates, STORE.tasks, budget["total_minor"] - budget["reserve_minor"] if budget else None, bool(budget["hard_limit"]) if budget else False, policy)
    result["currency"] = budget["currency"] if budget else None
    result["proposal_id"] = hashlib.sha256(json.dumps(sorted((a["task_id"], a["employee_id"]) for a in result["assignments"])).encode()).hexdigest()[:16]
    return result


def apply(project_id: str, proposal_id: str, actor: str, policy: Optional[Dict] = None) -> Dict:
    """Turns a proposal into approval requests. Nobody is committed to work until a manager approves each one."""
    proposal = propose(project_id, policy)
    if proposal["proposal_id"] != proposal_id or not proposal["assignments"]:
        raise HTTPException(409, "The team, tasks or rates changed since this plan was made. Review the new plan.")
    created = []
    with STORE.lock:
        for a in proposal["assignments"]:
            task, emp = STORE.task(a["task_id"]), STORE.employee(a["employee_id"])
            if task.assigned_to:
                continue
            emp.committed_hrs += task.estimated_hours
            task.assigned_to, task.status = emp.id, "PENDING_HITL_APPROVAL"
            impact = f" Estimated cost {a['estimated_cost_minor']} minor units." if a["estimated_cost_minor"] is not None else ""
            STORE.assignments.append(TaskAssignment(id=STORE.next_id("ASG"), task_id=task.id, employee_id=emp.id, suitability_score=a["suitability"]["score"],
                                                    factor_breakdown={"skill_match": a["suitability"]["skill"], "past_performance": a["suitability"]["record"]},
                                                    explanation_rationale=a["rationale"], tradeoffs_flagged=a["risks"], status="PENDING_HITL_APPROVAL"))
            approval = ApprovalRecord(approval_id=STORE.next_id("APR"), decision_id=f"OPT-{proposal_id}", kind="INITIAL_ALLOCATION", task_id=task.id, task_title=task.title, priority=task.priority,
                                      previous_owner=None, previous_owner_id=None, recommended_new_owner_id=emp.id, recommended_new_owner_name=emp.name, suitability_score=a["suitability"]["score"],
                                      post_utilization_pct=proposal["peak_utilization_pct"].get(emp.id, 0.0), explanation=f"Budget-aware plan {proposal_id}. {a['rationale']}{impact}", created_at=utcnow())
            STORE.approvals.append(approval)
            created.append(approval.approval_id)
        STORE.ledger.record(actor, "OPTIMIZED_PLAN_SUBMITTED", project_id, {"proposal": proposal_id, "approvals": created, "solver": proposal["solver"]["status"]})
    if created:
        STORE.notify("approval", f"{len(created)} assignment(s) need approval", "A budget-aware team plan is waiting for review.", audience_role="ADMIN")
    return {"status": "SUBMITTED_FOR_APPROVAL", "approvals": created, "proposal_id": proposal_id}
