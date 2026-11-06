"""Cost-aware team optimizer. Exact branch and bound in plain Python: small problems need no solver dependency.

Order of priority (nothing below may undo anything above):
  1. Eligibility: active employee, every required skill at or above the required level, suitability at or above the threshold.
  2. Schedule: the task's window (after its dependencies, before its deadline) must fit under the weekly capacity ceiling.
  3. Budget, when set: a plan that fits is always preferred, and it is never reached by relaxing 1 or 2.
  4. Among what remains, minimize:
       total labor cost
       + delivery_risk x sum(100 - suitability)
       + schedule_risk x number of assignments that push a week above the review threshold
       + imbalance     x highest weekly utilization in the plan (percentage points)
       + reassignment  x number of tasks moved from a current owner

Penalties are in minor currency units so they can be compared to cost. The defaults are a starting policy, not a validated
optimum; each company should set its own. Suitability is an explainable heuristic, not a probability of success.
Same inputs give the same plan: every ordering ties on ids.
"""
import math
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from .engine import PROFICIENCY_WEIGHTS
from .models import Employee, Task

HOURS_PER_WEEK_CEILING = 95.0
REVIEW_THRESHOLD = 85.0
DEFAULT_POLICY = {"delivery_risk": 2000, "schedule_risk": 50000, "imbalance": 1000, "reassignment": 100000, "min_suitability": 50.0}


def labor_cost(hours: float, hourly_minor: int) -> int:
    """Exact: goes through Decimal so currency totals never carry binary floating point error."""
    return int((Decimal(str(hours)) * Decimal(hourly_minor)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def suitability(emp: Employee, task: Task) -> Dict:
    """0-100. Skills 60%, delivery record 25%, deadline reliability 15%. People without evidence get a neutral 50, flagged, for the record parts."""
    skills = {s.skill_name: s for s in emp.skills}
    parts = []
    for name, level in task.required_skills.items():
        held = skills.get(name)
        parts.append(0.0 if not held else min(1.0, PROFICIENCY_WEIGHTS[held.level] / PROFICIENCY_WEIGHTS[level]) * (100.0 if held.is_verified else 80.0))
    skill_part = sum(parts) / len(parts) if parts else 70.0
    if emp.sufficient_evidence:
        record, reliability, flag = (emp.delivery_completion_rate + emp.work_quality_acceptance_rate) / 2, emp.deadline_reliability_rate, False
    else:
        record, reliability, flag = 50.0, 50.0, True
    return {"score": round(0.6 * skill_part + 0.25 * record + 0.15 * reliability, 2), "skill": round(skill_part, 1), "record": round(record, 1), "reliability": round(reliability, 1), "no_track_record": flag}


def gaps(emp: Employee, task: Task) -> List[str]:
    skills = {s.skill_name: s for s in emp.skills}
    missing = []
    for name, level in task.required_skills.items():
        held = skills.get(name)
        if not held:
            missing.append(f"{name} (needs {level})")
        elif PROFICIENCY_WEIGHTS[held.level] < PROFICIENCY_WEIGHTS[level]:
            missing.append(f"{name} at {held.level} (needs {level})")
    return missing


def task_windows(tasks: List[Task]) -> Dict[str, Tuple[int, int]]:
    """(first week, weeks) for each task. Work starts when its latest dependency is due; it can't be spread past its own deadline."""
    by_id = {t.id: t for t in tasks}
    windows = {}
    for t in tasks:
        start_day = max((by_id[d].deadline_days for d in t.dependencies if d in by_id), default=0)
        span = t.deadline_days - start_day
        windows[t.id] = (start_day // 7, max(1, math.ceil(span / 7)) if span > 0 else 0)
    return windows


def base_load(emp: Employee, assigned_hours: float) -> float:
    """Hours per week already spoken for that are not tasks being scheduled here: other commitments, meetings and leave."""
    return max(0.0, emp.committed_hrs - assigned_hours) + emp.meeting_hrs + emp.leave_hrs


@dataclass
class Candidate:
    employee_id: str
    name: str
    cost: int
    suit: Dict


@dataclass
class Result:
    status: str
    plan: Dict[str, str] = field(default_factory=dict)
    objective: Optional[float] = None
    nodes: int = 0
    gap: Optional[float] = None


def _search(tasks: List[Task], candidates: Dict[str, List[Candidate]], employees: Dict[str, Employee], baseline: Dict[str, Dict[int, float]], windows: Dict[str, Tuple[int, int]],
            policy: Dict, budget: Optional[int], current: Dict[str, Optional[str]], cost_only: bool, time_limit: float, node_limit: int) -> Result:
    order = sorted(tasks, key=lambda t: (len(candidates[t.id]), t.id))
    def additive(t: Task, c: Candidate) -> float:
        if cost_only:
            return c.cost
        return c.cost + policy["delivery_risk"] * (100.0 - c.suit["score"]) + (policy["reassignment"] if current.get(t.id) not in (None, c.employee_id) else 0)
    floors = [min(additive(t, c) for c in candidates[t.id]) for t in order]
    remaining = [sum(floors[i:]) for i in range(len(order) + 1)]
    cheapest = [min(c.cost for c in candidates[t.id]) for t in order]
    cheapest_left = [sum(cheapest[i:]) for i in range(len(order) + 1)]
    load = {e: dict(weeks) for e, weeks in baseline.items()}
    best: Dict = {"objective": math.inf, "plan": {}}
    state = {"nodes": 0, "stopped": False}
    deadline = time.monotonic() + time_limit
    choice: Dict[str, str] = {}

    def visit(i: int, total: float, cost: int, over: int, peak: float) -> None:
        if state["stopped"]:
            return
        state["nodes"] += 1
        if state["nodes"] >= node_limit or (state["nodes"] % 512 == 0 and time.monotonic() > deadline):
            state["stopped"] = True
            return
        if total + remaining[i] >= best["objective"] or (budget is not None and cost + cheapest_left[i] > budget):
            return
        if i == len(order):
            objective = total if cost_only else total + policy["schedule_risk"] * over + policy["imbalance"] * peak
            if objective < best["objective"]:
                best.update(objective=objective, plan=dict(choice))
            return
        task = order[i]
        first, weeks = windows[task.id]
        per_week = task.estimated_hours / weeks
        for c in sorted(candidates[task.id], key=lambda x: (additive(task, x), x.employee_id)):
            emp = employees[c.employee_id]
            ceiling = emp.weekly_capacity_hrs * HOURS_PER_WEEK_CEILING / 100.0
            weekly = load[c.employee_id]
            if any(weekly.get(w, weekly.get(-1, 0.0)) + per_week > ceiling + 1e-9 for w in range(first, first + weeks)):
                continue
            touched = {w: weekly.get(w, weekly.get(-1, 0.0)) for w in range(first, first + weeks)}
            for w in touched:
                weekly[w] = touched[w] + per_week
            highest = max(weekly[w] for w in touched) / max(emp.weekly_capacity_hrs, 1.0) * 100.0
            choice[task.id] = c.employee_id
            visit(i + 1, total + additive(task, c), cost + c.cost, over + (1 if highest > REVIEW_THRESHOLD else 0), max(peak, highest))
            for w, value in touched.items():
                weekly[w] = value
            del choice[task.id]

    visit(0, 0.0, 0, 0, 0.0)
    if best["objective"] is math.inf:
        return Result("stopped_without_plan" if state["stopped"] else "infeasible", nodes=state["nodes"])
    root = remaining[0]
    gap = round((best["objective"] - root) / best["objective"], 4) if state["stopped"] and best["objective"] else 0.0
    return Result("feasible_not_proven_optimal" if state["stopped"] else "optimal", best["plan"], best["objective"], state["nodes"], gap)


def optimize(tasks: List[Task], employees: List[Employee], rates: Dict[str, int], all_tasks: List[Task], budget_minor: Optional[int] = None, hard_budget: bool = False,
             policy: Optional[Dict] = None, current: Optional[Dict[str, Optional[str]]] = None, time_limit: float = 5.0, node_limit: int = 2_000_000) -> Dict:
    """Pure function: proposes a plan and changes nothing. rates maps employee id to hourly minor units; empty means cost is not considered."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    current = current or {}
    if not tasks:
        return {"status": "nothing_to_allocate", "assignments": [], "feasible": True, "cost_aware": bool(rates), "solver": {"status": "not_run", "nodes": 0, "gap": 0.0}}
    cost_aware = bool(rates)
    active = {e.id: e for e in employees if e.status not in ("Inactive", "On Leave")}
    windows = task_windows(tasks)
    candidates: Dict[str, List[Candidate]] = {}
    problems: List[Dict] = []
    for t in sorted(tasks, key=lambda x: x.id):
        pool: List[Candidate] = []
        reasons: List[str] = []
        if windows[t.id][1] == 0:
            problems.append({"task_id": t.id, "title": t.title, "reason": f"Deadline day {t.deadline_days} does not leave time after its dependencies finish.", "kind": "deadline_conflict",
                             "options": ["Move the deadline", "Reorder the dependencies", "Reduce scope"]})
            candidates[t.id] = []
            continue
        for emp in sorted(active.values(), key=lambda e: e.id):
            missing = gaps(emp, t)
            if missing:
                reasons.append(f"{emp.name}: missing {', '.join(missing)}")
                continue
            suit = suitability(emp, t)
            if suit["score"] < policy["min_suitability"]:
                reasons.append(f"{emp.name}: suitability {suit['score']} below the {policy['min_suitability']} threshold")
                continue
            if cost_aware and emp.id not in rates:
                reasons.append(f"{emp.name}: no approved cost rate")
                continue
            pool.append(Candidate(emp.id, emp.name, labor_cost(t.estimated_hours, rates[emp.id]) if cost_aware else 0, suit))
        candidates[t.id] = pool
        if not pool:
            problems.append({"task_id": t.id, "title": t.title, "reason": "No qualified candidate. " + ("; ".join(reasons[:4]) or "This organization has no available employees."), "kind": "skill_gap",
                             "options": ["Train a current employee", "Recruit or contract", "Assign a qualified mentor", "Change the deadline", "Revise the scope", "Reassess what the task requires"]})
    if problems:
        return {"status": "infeasible", "feasible": False, "assignments": [], "problems": problems, "cost_aware": cost_aware, "solver": {"status": "not_run", "nodes": 0, "gap": 0.0}}

    # Hours per week already taken, by week. -1 is the flat baseline for any week without scheduled tasks.
    ids = {t.id for t in tasks}
    baseline: Dict[str, Dict[int, float]] = {}
    for emp in active.values():
        mine = [t for t in all_tasks if t.assigned_to == emp.id and t.id not in ids and t.status != "COMPLETED_AND_AUDITED"]
        flat = base_load(emp, sum(t.estimated_hours for t in mine))
        weeks: Dict[int, float] = {-1: flat}
        other = task_windows(mine)
        for t in mine:
            first, span = other[t.id]
            span = max(span, 1)
            for w in range(first, first + span):
                weeks[w] = weeks.get(w, flat) + t.estimated_hours / span
        baseline[emp.id] = weeks

    limit = budget_minor if budget_minor is not None else None
    result = _search(tasks, candidates, active, baseline, windows, policy, limit, current, False, time_limit, node_limit)
    response: Dict = {"cost_aware": cost_aware, "policy": policy, "budget_minor": budget_minor, "hard_budget": hard_budget}
    over_budget = None
    if result.status in ("infeasible", "stopped_without_plan") and budget_minor is not None:
        # The budget is the problem only if a plan exists without it. Find the cheapest; qualifications are never relaxed to fit.
        cheapest = _search(tasks, candidates, active, baseline, windows, policy, None, current, True, time_limit, node_limit)
        if cheapest.plan:
            total = sum(next(c.cost for c in candidates[t]if c.employee_id == e) for t, e in cheapest.plan.items())
            over_budget = {"lowest_feasible_cost_minor": total, "overrun_minor": total - budget_minor, "plan": cheapest.plan,
                           "why": "Even the cheapest qualified team with room in its schedule costs more than the budget. Qualifications were not lowered to fit.",
                           "options": ["Increase the budget", "Reduce scope", "Move the deadline to widen the choice of people", "Train lower-cost employees", "Contract specialist work"]}
            result = cheapest if not hard_budget else result
    if not result.plan:
        return {**response, "status": "over_budget" if over_budget else "infeasible", "feasible": False, "assignments": [], "over_budget": over_budget,
                "problems": [] if over_budget else [{"task_id": None, "title": "Whole plan", "kind": "capacity", "reason": "The qualified people do not have enough weekly capacity for these tasks by their deadlines.",
                                                     "options": ["Move deadlines", "Reduce scope", "Free up commitments", "Add capacity"]}],
                "solver": {"status": result.status, "nodes": result.nodes, "gap": result.gap}}

    assignments = []
    for t in sorted(tasks, key=lambda x: x.id):
        c = next(x for x in candidates[t.id] if x.employee_id == result.plan[t.id])
        emp = active[c.employee_id]
        first, weeks = windows[t.id]
        risks = (["No track record yet: scored as neutral, not as strong or weak."] if c.suit["no_track_record"] else []) + ([f"Unverified skill evidence for {t.id}."] if c.suit["skill"] < 100 and c.suit["skill"] >= 70 else [])
        assignments.append({"task_id": t.id, "task_title": t.title, "employee_id": c.employee_id, "employee_name": c.name, "required_skills": t.required_skills, "suitability": c.suit,
                            "estimated_hours": t.estimated_hours, "estimated_cost_minor": c.cost if cost_aware else None, "hours_per_week": round(t.estimated_hours / weeks, 2), "weeks": [first, first + weeks - 1],
                            "existing_weekly_hours": round(baseline[c.employee_id].get(-1, 0.0), 2), "weekly_capacity": emp.weekly_capacity_hrs,
                            "rationale": f"{c.name} holds every required skill (skill fit {c.suit['skill']}, suitability {c.suit['score']})" + (f" and costs {c.cost} minor units for {t.estimated_hours}h." if cost_aware else "."), "risks": risks})
    total_cost = sum(a["estimated_cost_minor"] or 0 for a in assignments)
    weekly = {e: dict(w) for e, w in baseline.items()}
    for a in assignments:
        for w in range(a["weeks"][0], a["weeks"][1] + 1):
            weekly[a["employee_id"]][w] = weekly[a["employee_id"]].get(w, weekly[a["employee_id"]].get(-1, 0.0)) + a["hours_per_week"]
    peaks = {e: round(max(v.values()) / max(active[e].weekly_capacity_hrs, 1.0) * 100.0, 1) for e, v in weekly.items() if any(a["employee_id"] == e for a in assignments)}
    return {**response, "status": "over_budget_review_required" if over_budget else "feasible", "feasible": True, "assignments": assignments, "total_cost_minor": total_cost if cost_aware else None,
            "over_budget": over_budget, "peak_utilization_pct": peaks, "objective": result.objective,
            "solver": {"status": result.status, "nodes": result.nodes, "gap": result.gap},
            "explanation": "Hard constraints were applied first, then cost and penalties were minimized. Scores are explainable heuristics, not probabilities of success."}
