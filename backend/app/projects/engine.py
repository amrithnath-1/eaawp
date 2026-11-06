"""Deterministic computation & constraint engine (layer 4).

Everything here is pure Python math: capacity, the 6 disaggregated scores,
hard-constraint filtering, weighted suitability scoring, Gini fairness and DAG
analysis. The LLM/agent layer never decides an assignment on its own.
"""
from typing import Dict, List, Optional

from .models import Employee, Task, WeightConfig

PROFICIENCY_WEIGHTS = {"Beginner": 0.40, "Intermediate": 0.70, "Advanced": 0.90, "Expert": 1.00}
HARD_CAPACITY_CEILING = 95.0
HITL_LOAD_THRESHOLD = 85.0


# ------------------------------------------------------------ 4.1 capacity
def net_free_hrs(emp: Employee) -> float:
    if emp.status in ("On Leave", "Inactive"):
        return 0.0
    return max(0.0, round(emp.weekly_capacity_hrs - (emp.committed_hrs + emp.meeting_hrs + emp.leave_hrs), 2))


def util_pct(emp: Employee, extra_hrs: float = 0.0) -> float:
    used = emp.committed_hrs + emp.meeting_hrs + emp.leave_hrs + extra_hrs
    return round((used / max(emp.weekly_capacity_hrs, 1.0)) * 100.0, 1)


def workload_estimate(emp: Employee) -> Dict:
    u = util_pct(emp)
    return {
        "employee_id": emp.id,
        "committed_hrs": emp.committed_hrs,
        "free_capacity_hrs": net_free_hrs(emp),
        "utilization_pct": u,
        "is_overloaded": u > HITL_LOAD_THRESHOLD,
    }


# ------------------------------------------------------------ 4.2 / 4.3 scores
def level_for(perf_score: float, sufficient_evidence: bool) -> str:
    if not sufficient_evidence:
        return "Insufficient Evidence (New Hire Onboarding)"
    if perf_score >= 90:
        return "Level 5 — Exceptional"
    if perf_score >= 75:
        return "Level 4 — Advanced"
    if perf_score >= 60:
        return "Level 3 — Competent"
    if perf_score >= 40:
        return "Level 2 — Progressing"
    return "Level 1 — Developing"


def skill_score(emp: Employee) -> float:
    if not emp.skills:
        return 50.0
    vals = [PROFICIENCY_WEIGHTS[s.level] * 100.0 * (1.0 if s.is_verified else 0.82) for s in emp.skills]
    return min(100.0, round(sum(vals) / len(vals), 1))


def compute_6_scores(emp: Employee) -> Dict:
    s_skill = skill_score(emp)
    perf = round(
        0.25 * emp.delivery_completion_rate
        + 0.25 * emp.work_quality_acceptance_rate
        + 0.20 * s_skill
        + 0.15 * emp.deadline_reliability_rate
        + 0.10 * emp.collaboration_review_score
        + 0.05 * emp.learning_improvement_score,
        1,
    )
    return {
        "employee_id": emp.id,
        "name": emp.name,
        "email": emp.email,
        "designation": emp.designation,
        "department": emp.department,
        "manager": emp.manager,
        "years_exp": emp.years_exp,
        "status": emp.status,
        "weekly_capacity_hrs": emp.weekly_capacity_hrs,
        "committed_hrs": emp.committed_hrs,
        "meeting_hrs": emp.meeting_hrs,
        "leave_hrs": emp.leave_hrs,
        "free_capacity_hrs": net_free_hrs(emp),
        "skill_score": s_skill,
        # New hires are protected: the score is withheld rather than shown low.
        "performance_score": perf if emp.sufficient_evidence else None,
        "availability_score": round((net_free_hrs(emp) / max(emp.weekly_capacity_hrs, 1.0)) * 100.0, 1),
        "workload_score": util_pct(emp),
        "collaboration_score": round(emp.collaboration_review_score, 1),
        "level": level_for(perf, emp.sufficient_evidence),
        "sufficient_evidence": emp.sufficient_evidence,
        "dispute_status": emp.dispute_status,
        "dispute_note": emp.dispute_note,
        "preferred_tasks": emp.preferred_tasks,
        "learning_goals": emp.learning_goals,
        "evidence_metrics": {
            "delivery_completion_rate": emp.delivery_completion_rate,
            "work_quality_acceptance_rate": emp.work_quality_acceptance_rate,
            "deadline_reliability_rate": emp.deadline_reliability_rate,
            "collaboration_review_score": emp.collaboration_review_score,
            "learning_improvement_score": emp.learning_improvement_score,
        },
        "skills": [s.model_dump() for s in emp.skills],
    }


def _raw_perf(emp: Employee) -> float:
    return round(
        0.25 * emp.delivery_completion_rate
        + 0.25 * emp.work_quality_acceptance_rate
        + 0.20 * skill_score(emp)
        + 0.15 * emp.deadline_reliability_rate
        + 0.10 * emp.collaboration_review_score
        + 0.05 * emp.learning_improvement_score,
        1,
    )


# ------------------------------------------------------------ suitability
def score_candidate_for_task(emp: Employee, task: Task, weights: WeightConfig) -> Dict:
    """Stage 1 hard-constraint filter + stage 2 weighted multi-factor scorer."""
    skill_map = {s.skill_name: s for s in emp.skills}
    violations: List[str] = []
    warnings: List[str] = []

    if emp.status == "Inactive":
        violations.append("Employee record is INACTIVE.")
    if emp.status == "On Leave":
        violations.append("Employee is currently ON_LEAVE.")
    free = net_free_hrs(emp)
    if free < task.estimated_hours:
        violations.append(f"Insufficient free capacity ({free}h free vs {task.estimated_hours}h required).")
    post_u = util_pct(emp, task.estimated_hours)
    if post_u > HARD_CAPACITY_CEILING:
        violations.append(f"Breaches {HARD_CAPACITY_CEILING:.0f}% hard capacity ceiling ({post_u}%).")
    elif post_u > HITL_LOAD_THRESHOLD:
        warnings.append(f"High utilization warning ({post_u}% post-assignment).")

    matched_scores: List[float] = []
    missing: List[str] = []
    for req_sk, req_lvl in task.required_skills.items():
        if req_sk in skill_map:
            es = skill_map[req_sk]
            ratio = min(1.15, PROFICIENCY_WEIGHTS[es.level] / PROFICIENCY_WEIGHTS[req_lvl])
            v_bonus = 1.08 if es.is_verified else 0.85
            matched_scores.append(min(100.0, ratio * v_bonus * 90.0))
            if task.priority == "Critical" and not es.is_verified:
                warnings.append(f"Skill '{req_sk}' is self-reported (unverified) for a Critical task.")
        else:
            missing.append(req_sk)
            matched_scores.append(0.0)

    if task.required_skills and len(missing) == len(task.required_skills):
        violations.append(f"Zero required domain skills matched ({', '.join(missing)}).")
    elif task.priority == "Critical" and missing:
        violations.append(f"Missing mandatory skill for Critical task: {', '.join(missing)}.")
    elif missing:
        warnings.append(f"Partial skill gap: {', '.join(missing)}.")

    s_skill = round(sum(matched_scores) / max(len(matched_scores), 1), 1)
    if free >= task.estimated_hours:
        s_avail = round(min(100.0, (free / max(task.estimated_hours, 1.0)) * 80.0), 1)
    else:
        s_avail = round((free / task.estimated_hours) * 40.0, 1)
    s_balance = round(max(0.0, 100.0 - post_u), 1)
    if task.priority in ("Critical", "High"):
        s_prio = round(0.6 * emp.deadline_reliability_rate + 0.4 * emp.work_quality_acceptance_rate, 1)
    else:
        s_prio = 80.0
    s_perf = _raw_perf(emp)
    if any(k in emp.learning_goals for k in task.required_skills):
        s_growth = 95.0
    elif any(k in emp.preferred_tasks for k in task.required_skills):
        s_growth = 85.0
    else:
        s_growth = 55.0

    total = round(
        weights.skill_match * s_skill
        + weights.availability * s_avail
        + weights.workload_balance * s_balance
        + weights.priority_alignment * s_prio
        + weights.past_performance * s_perf
        + weights.development_opportunity * s_growth,
        2,
    )
    eligible = not violations
    return {
        "employee_id": emp.id,
        "employee_name": emp.name,
        "designation": emp.designation,
        "eligible": eligible,
        "suitability_score": total if eligible else round(total * 0.35, 2),
        "free_hrs_before": free,
        "utilization_after_pct": post_u,
        "factor_breakdown": {
            "skill_match": s_skill,
            "availability": s_avail,
            "workload_balance": s_balance,
            "priority_alignment": s_prio,
            "past_performance": s_perf,
            "growth_opportunity": s_growth,
        },
        "hard_violations": violations,
        "warnings": warnings,
        "new_hire_protected": not emp.sufficient_evidence,
    }


def rank_candidates(employees: List[Employee], task: Task, weights: WeightConfig,
                    exclude: Optional[str] = None) -> List[Dict]:
    """Rank candidates; ties broken by lower post-load, then stable employee id."""
    cands = [score_candidate_for_task(e, task, weights) for e in employees if e.id != exclude and e.status != "Inactive"]
    cands.sort(key=lambda c: (not c["eligible"], -c["suitability_score"], c["utilization_after_pct"], c["employee_id"]))
    return cands


# ------------------------------------------------------------ 4.4 fairness
def gini(values: List[float]) -> float:
    arr = sorted(values)
    n = len(arr)
    if not n or not sum(arr):
        return 0.0
    return round((2.0 * sum((i + 1) * v for i, v in enumerate(arr))) / (n * sum(arr)) - (n + 1.0) / n, 4)


def team_gini(employees: List[Employee]) -> float:
    return gini([util_pct(e) for e in employees if e.status not in ("On Leave", "Inactive")])


# ------------------------------------------------------------ DAG
def detect_cycle(tasks: List[Task]) -> Optional[List[str]]:
    graph = {t.id: list(t.dependencies) for t in tasks}
    color: Dict[str, int] = {}
    stack: List[str] = []

    def visit(node: str) -> Optional[List[str]]:
        color[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if color.get(dep) == 1:
                return stack[stack.index(dep):] + [dep]
            if color.get(dep, 0) == 0 and dep in graph:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        color[node] = 2
        return None

    for t in graph:
        if color.get(t, 0) == 0:
            found = visit(t)
            if found:
                return found
    return None


def topo_sort(tasks: List[Task]) -> List[Task]:
    """Kahn's algorithm; ties keep original order so results are deterministic."""
    by_id = {t.id: t for t in tasks}
    indeg = {t.id: sum(1 for d in t.dependencies if d in by_id) for t in tasks}
    order: List[Task] = []
    ready = [t.id for t in tasks if indeg[t.id] == 0]
    while ready:
        tid = ready.pop(0)
        order.append(by_id[tid])
        for t in tasks:
            if tid in t.dependencies:
                indeg[t.id] -= 1
                if indeg[t.id] == 0:
                    ready.append(t.id)
    if len(order) != len(tasks):
        raise ValueError("Dependency cycle detected")
    return order


def critical_path(tasks: List[Task]) -> Dict:
    """Longest effort path through the DAG (hours) and its task ids."""
    order = topo_sort(tasks)
    by_id = {t.id: t for t in tasks}
    finish: Dict[str, float] = {}
    prev: Dict[str, Optional[str]] = {}
    for t in order:
        best, best_dep = 0.0, None
        for d in t.dependencies:
            if d in finish and finish[d] > best:
                best, best_dep = finish[d], d
        finish[t.id] = best + t.estimated_hours
        prev[t.id] = best_dep
    if not finish:
        return {"path": [], "total_hours": 0.0}
    end = max(finish, key=lambda k: finish[k])
    path = []
    cur: Optional[str] = end
    while cur:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return {"path": path, "total_hours": round(finish[end], 1),
            "earliest_finish": {k: round(v, 1) for k, v in finish.items()},
            "titles": {k: by_id[k].title for k in path}}


def dependencies_planned(task: Task, tasks: List[Task]) -> bool:
    """A task can be allocated once every prerequisite has an owner (planned) or is done."""
    by_id = {t.id: t for t in tasks}
    for d in task.dependencies:
        dep = by_id.get(d)
        if dep is None:
            return False
        if dep.assigned_to is None and dep.status != "COMPLETED_AND_AUDITED":
            return False
    return True
