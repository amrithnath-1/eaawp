"""Multi-agent orchestration layer (ported from Vyuham): 7 logical agents as modules.

EAAWP note: the model-written decomposition lives in workflow.py (Gemini through the EAAWP gateway); this catalogue is the
labelled rule-based fallback.

Agents decide *what to do next* and explain it; every number comes from engine.py.
Mutations only happen through these functions while holding STORE.lock, and every
significant step is written to the hash-chained audit ledger.
"""
import re
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

from . import engine
from .audit import utcnow
from .models import AgentDecision, ApprovalRecord, Deliverable, Employee, Task, TaskAssignment
from .store import STORE

PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _decision(agent: str, trigger: str, shortlist: List[Dict], action: str, risk: str, needs_approval: bool) -> AgentDecision:
    d = AgentDecision(id=STORE.next_id("DEC"), agent_name=agent, trigger_event=trigger,
                      shortlist=[{k: c[k] for k in ("employee_id", "employee_name", "suitability_score", "eligible")} for c in shortlist[:4]],
                      recommended_action=action, risk_level=risk, requires_approval=needs_approval, created_at=utcnow())
    STORE.decisions.insert(0, d)
    return d


def _explain(task: Task, winner: Dict, runner_up: Optional[Dict], disqualified: List[Dict]) -> str:
    fb = winner["factor_breakdown"]
    parts = [
        f"Recommended {winner['employee_name']} ({winner['designation']}) with Suitability {winner['suitability_score']}/100.",
        f"Skill Match: {fb['skill_match']}%, Free Capacity: {winner['free_hrs_before']}h -> {winner['utilization_after_pct']}% post-load.",
    ]
    if runner_up:
        gap = round(winner["suitability_score"] - runner_up["suitability_score"], 2)
        parts.append(f"Runner-up {runner_up['employee_name']} scored {runner_up['suitability_score']}/100 ({gap} pts behind).")
    if disqualified:
        d = disqualified[0]
        parts.append(f"Disqualified {d['employee_name']}: {'; '.join(d['hard_violations'])}")
    if winner["warnings"]:
        parts.append("Trade-offs: " + " ".join(winner["warnings"]))
    return " ".join(parts)


# =================================================================== Agent 1
class ProjectAnalysisAgent:
    """Decomposes a project brief into DAG tasks with skills, effort and dependencies."""
    name = "Agent 1 (Project Analysis)"

    # (key, keywords that trigger it, title, skills, base hours, priority, depends-on keys, deliverable)
    CATALOG = [
        ("req", None, "Requirements & Domain Modeling", {"Requirements Analysis": "Advanced"}, 8, "High", [], "Approved PRD + acceptance criteria"),
        ("ux", ["ui", "ux", "app", "portal", "dashboard", "website", "web", "mobile", "screen", "design"], "UX Flows & Design System",
         {"UI/UX Design": "Advanced"}, 10, "High", ["req"], "Figma prototype + design tokens"),
        ("db", ["data", "database", "store", "record", "crm", "inventory", "tenant", "report", "analytics", "sql"], "Data Model & Database Schema",
         {"PostgreSQL": "Advanced", "Python": "Intermediate"}, 10, "Critical", ["req"], "Migrations + indexed schema"),
        ("api", ["api", "backend", "service", "platform", "integrat", "system", "workflow", "portal", "app", "crm"], "Backend API & Business Logic",
         {"FastAPI": "Advanced", "Python": "Advanced"}, 14, "Critical", ["db"], "OpenAPI spec + unit tests"),
        ("ml", ["ai", "ml", "predict", "scoring", "recommend", "forecast", "classif", "intelligen", "churn", "model"], "AI/ML Model & Inference Service",
         {"Machine Learning": "Advanced", "Python": "Advanced"}, 12, "High", ["db"], "Model service + evaluation report"),
        ("fe", ["ui", "app", "portal", "dashboard", "website", "web", "frontend", "screen", "crm"], "Frontend Application",
         {"React": "Advanced", "TypeScript": "Intermediate"}, 16, "High", ["ux", "api"], "Responsive SPA + accessibility pass"),
        ("docs", ["doc", "compliance", "policy", "guide", "training", "manual"], "Documentation & Compliance Pack",
         {"Tech Writing": "Advanced"}, 6, "Medium", ["api"], "User guide + compliance checklist"),
        ("qa", None, "QA Automation & Security Testing", {"QA Automation": "Advanced", "Security Testing": "Intermediate"}, 12, "Critical",
         ["api", "fe"], "Regression + OWASP suite green"),
        ("ops", None, "CI/CD & Production Deployment", {"Docker & Kubernetes": "Advanced", "CI/CD Pipelines": "Advanced"}, 10, "High",
         ["qa"], "Live URL + runbook"),
    ]

    def _decompose_heuristic(self, objective: str, priority: str, deadline_days: int) -> List[Dict]:
        text = objective.lower()
        def mentions(word: str) -> bool:     # short words must match whole ("ai" must not match "retail")
            return bool(re.search(rf"\b{re.escape(word)}\b" if len(word) <= 3 else rf"\b{re.escape(word)}", text))

        chosen = {key for key, kws, *_ in self.CATALOG if kws is None or any(mentions(k) for k in kws)}
        # Effort scales with scope implied by the brief's length and the deadline.
        scale = 1.0 + min(0.5, len(text) / 2000) - (0.2 if deadline_days < 14 else 0.0)
        drafts, n = [], len([c for c in self.CATALOG if c[0] in chosen])
        for i, (key, _kws, title, skills, hrs, prio, deps, deliv) in enumerate([c for c in self.CATALOG if c[0] in chosen]):
            live_deps = self._resolve_deps(deps, chosen)
            if priority == "Critical" and prio == "High":
                prio = "Critical" if key in ("api", "qa") else prio
            drafts.append({"key": key, "title": title, "description": f"{title} for: {objective[:140]}",
                           "required_skills": skills, "estimated_hours": round(hrs * scale),
                           "priority": prio, "deadline_days": max(2, round(deadline_days * (i + 1) / n)),
                           "depends_on_keys": live_deps, "deliverable_criteria": deliv})
        return drafts

    def _resolve_deps(self, deps: List[str], chosen: set) -> List[str]:
        """If a dependency was not selected, inherit its own dependencies instead."""
        by_key = {c[0]: c for c in self.CATALOG}
        out: List[str] = []
        for d in deps:
            if d in chosen:
                out.append(d)
            else:
                out.extend(x for x in self._resolve_deps(by_key[d][6], chosen) if x not in out)
        return out


# =================================================================== Agent 2
class WorkforceIntelligenceAgent:
    name = "Agent 2 (Workforce Intelligence)"

    def skill_gaps(self) -> Dict:
        demand: Dict[str, Dict] = {}
        for t in STORE.tasks:
            if t.status == "COMPLETED_AND_AUDITED":
                continue
            for sk, lvl in t.required_skills.items():
                d = demand.setdefault(sk, {"skill": sk, "required_level": lvl, "tasks": [], "demand_hrs": 0.0})
                d["tasks"].append(t.id)
                d["demand_hrs"] += t.estimated_hours
                if engine.PROFICIENCY_WEIGHTS[lvl] > engine.PROFICIENCY_WEIGHTS[d["required_level"]]:
                    d["required_level"] = lvl
        rows = []
        for sk, d in demand.items():
            need = engine.PROFICIENCY_WEIGHTS[d["required_level"]]
            verified = [e for e in STORE.employees if any(s.skill_name == sk and s.is_verified and engine.PROFICIENCY_WEIGHTS[s.level] >= need for s in e.skills)]
            self_rep = [e for e in STORE.employees if any(s.skill_name == sk and not s.is_verified for s in e.skills)]
            available = [e for e in verified if e.status != "On Leave" and engine.net_free_hrs(e) > 0]
            learners = [e for e in STORE.employees if sk in e.learning_goals]
            supply_hrs = sum(engine.net_free_hrs(e) for e in available)
            if not verified:
                severity = "Critical"
            elif len(verified) == 1:
                severity = "High"   # single point of failure (bus factor 1)
            elif supply_hrs < d["demand_hrs"]:
                severity = "Medium"
            else:
                severity = "Low"
            rows.append({**d, "verified_holders": [e.name for e in verified], "self_reported_holders": [e.name for e in self_rep],
                         "available_holders": len(available), "supply_hrs": round(supply_hrs, 1), "severity": severity,
                         "training_recommendations": [{"employee_id": e.id, "name": e.name,
                                                       "recommendation": f"Pair with {verified[0].name if verified else 'external mentor'} on {sk} ({d['required_level']})"}
                                                      for e in learners]})
        rows.sort(key=lambda r: (["Critical", "High", "Medium", "Low"].index(r["severity"]), r["skill"]))
        return {"agent": self.name, "gaps": rows}


# =================================================================== Agent 3
class TaskAllocationAgent:
    name = "Agent 3 (Task Allocation)"

    def allocate_all(self, actor: str, project_id: Optional[str] = None) -> Dict:
        with STORE.lock:
            gini_before = engine.team_gini(STORE.employees)
            results = []
            for task in engine.topo_sort(STORE.tasks):
                if project_id and task.project_id != project_id:
                    continue
                if task.assigned_to or task.status not in ("READY_FOR_ALLOCATION", "BLOCKED_BY_DEPENDENCY", "DRAFT_GENERATED"):
                    continue
                if not engine.dependencies_planned(task, STORE.tasks):
                    task.status = "BLOCKED_BY_DEPENDENCY"
                    results.append({"task_id": task.id, "task_title": task.title, "priority": task.priority, "status": task.status,
                                    "recommended": None, "shortlist": [], "explanation": "Waiting for prerequisite tasks to be planned or completed."})
                    continue
                results.append(self._allocate_one(task, actor))
            gini_after = engine.team_gini(STORE.employees)
            STORE.ledger.record(actor, "ALLOCATION_RUN_COMPLETED", "PRJ-ALL",
                                {"tasks": len(results), "gini_before": gini_before, "gini_after": gini_after,
                                 "weights": STORE.weights.model_dump()})
            return {"agent": self.name, "allocated_count": sum(1 for r in results if r["recommended"] and r["recommended"]["eligible"]),
                    "gini_before": gini_before, "gini_after": gini_after, "allocations": results}

    def _allocate_one(self, task: Task, actor: str) -> Dict:
        task.status = "CANDIDATES_SCORED"
        cands = engine.rank_candidates(STORE.employees, task, STORE.weights)
        if not cands:       # a company with no employees yet
            task.status = "READY_FOR_ALLOCATION"
            return {"task_id": task.id, "task_title": task.title, "priority": task.priority, "status": "UNASSIGNED_INFEASIBLE",
                    "recommended": None, "shortlist": [], "explanation": "No eligible candidate: this organization has no employees yet."}
        winner = cands[0]
        runner_up = next((c for c in cands[1:] if c["eligible"]), None)
        disq = [c for c in cands if not c["eligible"]]
        explanation = _explain(task, winner, runner_up, disq)
        if not winner["eligible"]:
            task.status = "READY_FOR_ALLOCATION"
            dec = _decision(self.name, f"ALLOCATE {task.id}", cands, "ESCALATE: no eligible candidate", "High", True)
            STORE.ledger.record(actor, "ALLOCATION_INFEASIBLE", task.id, {"reasons": winner["hard_violations"], "decision": dec.id})
            return {"task_id": task.id, "task_title": task.title, "priority": task.priority, "status": "UNASSIGNED_INFEASIBLE",
                    "recommended": winner, "shortlist": cands[:4], "explanation": "No eligible candidate. " + explanation}

        emp = STORE.employee(winner["employee_id"])
        emp.committed_hrs += task.estimated_hours        # capacity is reserved immediately
        task.assigned_to = emp.id
        needs_hitl = task.priority == "Critical" or winner["utilization_after_pct"] > engine.HITL_LOAD_THRESHOLD
        dec = _decision(self.name, f"ALLOCATE {task.id}", cands, f"ASSIGN {task.id} -> {emp.id}",
                        "High" if needs_hitl else "Low", needs_hitl)
        asg = TaskAssignment(id=STORE.next_id("ASG"), task_id=task.id, employee_id=emp.id, suitability_score=winner["suitability_score"],
                             factor_breakdown=winner["factor_breakdown"], explanation_rationale=explanation,
                             tradeoffs_flagged=winner["warnings"], status="PENDING_HITL_APPROVAL" if needs_hitl else "ACTIVE")
        STORE.assignments.append(asg)
        approval_id = None
        if needs_hitl:
            task.status = "PENDING_HITL_APPROVAL"
            why = "Critical-priority task" if task.priority == "Critical" else f"post-load {winner['utilization_after_pct']}% > 85%"
            apr = ApprovalRecord(approval_id=STORE.next_id("APR"), decision_id=dec.id, kind="INITIAL_ALLOCATION", task_id=task.id,
                                 task_title=task.title, priority=task.priority, previous_owner=None, previous_owner_id=None,
                                 recommended_new_owner_id=emp.id, recommended_new_owner_name=emp.name,
                                 suitability_score=winner["suitability_score"], post_utilization_pct=winner["utilization_after_pct"],
                                 explanation=f"HITL required ({why}). {explanation}", shortlist=cands[:4], created_at=utcnow())
            STORE.approvals.append(apr)
            approval_id = apr.approval_id
        else:
            task.status = "ASSIGNED"
        STORE.ledger.record("AGENT_3_ALLOCATOR", "TASK_ALLOCATED", task.id,
                            {"winner": emp.id, "score": winner["suitability_score"], "post_load": winner["utilization_after_pct"],
                             "status": task.status, "approval_id": approval_id})
        return {"task_id": task.id, "task_title": task.title, "priority": task.priority, "status": task.status,
                "approval_id": approval_id, "recommended": winner, "shortlist": cands[:4], "explanation": explanation}

    def what_if(self, task_id: str, employee_id: str) -> Dict:
        """Counterfactual: what happens if this employee takes this task? Nothing is mutated."""
        with STORE.lock:
            task, emp = STORE.task(task_id), STORE.employee(employee_id)
            cand = engine.score_candidate_for_task(emp, task, STORE.weights)
            ranked = engine.rank_candidates(STORE.employees, task, STORE.weights)
            utils = {e.id: engine.util_pct(e) for e in STORE.employees if e.status != "On Leave"}
            before = engine.gini(list(utils.values()))
            hrs = task.estimated_hours
            prev = STORE.find_employee(task.assigned_to)
            if prev and prev.id in utils:
                utils[prev.id] = round(utils[prev.id] - hrs / prev.weekly_capacity_hrs * 100, 1)
            if emp.id in utils:
                utils[emp.id] = round(utils[emp.id] + hrs / emp.weekly_capacity_hrs * 100, 1)
            after = engine.gini(list(utils.values()))
            best = ranked[0]
            return {"agent": self.name, "task_id": task.id, "task_title": task.title, "candidate": cand,
                    "rank": next(i + 1 for i, c in enumerate(ranked) if c["employee_id"] == emp.id),
                    "best_alternative": best, "gini_before": before, "gini_after": after,
                    "verdict": ("Feasible" if cand["eligible"] else "Blocked by hard constraints: " + "; ".join(cand["hard_violations"]))}


# =================================================================== Agent 4
class ProgressMonitoringAgent:
    name = "Agent 4 (Progress Monitoring)"

    def report(self) -> Dict:
        by_id = {t.id: t for t in STORE.tasks}
        rows = []
        for t in STORE.tasks:
            incomplete = [d for d in t.dependencies if by_id.get(d) and by_id[d].status != "COMPLETED_AND_AUDITED"]
            owner = STORE.find_employee(t.assigned_to)
            blockers = []
            if t.status == "IN_PROGRESS" and incomplete:
                blockers.append(f"Started before prerequisites finished: {', '.join(incomplete)}")
            if owner and owner.status == "On Leave":
                blockers.append(f"Owner {owner.name} is on leave")
            rows.append({"task_id": t.id, "title": t.title, "status": t.status, "progress_pct": t.progress_pct,
                         "owner": owner.name if owner else None, "incomplete_prerequisites": incomplete, "blockers": blockers})
        done = sum(1 for t in STORE.tasks if t.status == "COMPLETED_AND_AUDITED")
        return {"agent": self.name, "completed": done, "total": len(STORE.tasks),
                "velocity_pct": round(sum(t.progress_pct for t in STORE.tasks) / max(len(STORE.tasks), 1), 1), "tasks": rows}

    def update_progress(self, task_id: str, employee_id: str, pct: int, status: Optional[str], actor: str) -> Dict:
        with STORE.lock:
            t = STORE.task(task_id)
            if t.assigned_to != employee_id:
                raise HTTPException(403, "You can only update tasks assigned to you")
            if t.status in ("PENDING_HITL_APPROVAL", "AT_RISK_DISRUPTED", "REALLOCATION_PROPOSED"):
                raise HTTPException(409, f"Task is {t.status}; wait for manager approval")
            if t.status == "COMPLETED_AND_AUDITED":
                raise HTTPException(409, "This task is already completed and verified")
            before = {"status": t.status, "progress_pct": t.progress_pct}
            t.progress_pct = pct
            t.status = status or ("IN_PROGRESS" if pct < 100 else "DELIVERABLE_IN_REVIEW")
            t.activity.append({"at": utcnow(), "actor": actor, "text": f"Reported {pct}% ({t.status.replace('_', ' ').lower()})"})
            STORE.ledger.record(actor, "TASK_PROGRESS_UPDATED", t.id, {"before": before, "after": {"status": t.status, "progress_pct": pct}})
            return t.model_dump()

    def accept_deliverable(self, task_id: str, actor: str) -> Dict:
        with STORE.lock:
            t = STORE.task(task_id)
            if t.status != "DELIVERABLE_IN_REVIEW":
                raise HTTPException(409, "Only deliverables in review can be accepted")
            t.status, t.progress_pct = "COMPLETED_AND_AUDITED", 100
            emp = STORE.find_employee(t.assigned_to)
            if emp:
                emp.committed_hrs = max(0.0, emp.committed_hrs - t.estimated_hours)
                reworks = sum(1 for a in t.activity if a["text"].startswith("Rework requested"))
                STORE.deliverables.append(Deliverable(id=f"DLV-{len(STORE.deliverables) + 301}", task_id=t.id, employee_id=emp.id, accepted=True,
                                                      rework_count=reworks, complexity_weight=round(1 + (t.complexity - 3) * 0.1, 2)))
            t.activity.append({"at": utcnow(), "actor": actor, "text": "Deliverable accepted; counted as verified progress"})
            STORE.ledger.record(actor, "DELIVERABLE_ACCEPTED", t.id, {"owner": t.assigned_to, "criteria": t.deliverable_criteria})
            return t.model_dump()


# =================================================================== Agent 5
class PerformanceEvaluationAgent:
    name = "Agent 5 (Performance Evaluation)"

    def evaluate(self, emp_id: str) -> Dict:
        emp = STORE.employee(emp_id)
        scores = engine.compute_6_scores(emp)
        dels = [d for d in STORE.deliverables if d.employee_id == emp_id]
        events = [e.model_dump() for e in STORE.integration_events if e.employee_id == emp_id]
        evidence = {
            "deliverables": [d.model_dump() for d in dels],
            "accepted_deliverables": sum(1 for d in dels if d.accepted),
            "rework_total": sum(d.rework_count for d in dels),
            "complexity_weighted_output": round(sum(d.complexity_weight for d in dels if d.accepted), 2),
            "integration_events": events,
            "excluded_signals": ["commit counts", "lines of code", "online status", "hours logged", "personal social media"],
        }
        tasks = [t.model_dump() for t in STORE.tasks if t.assigned_to == emp_id]
        return {"agent": self.name, "scores": scores, "evidence": evidence, "tasks": tasks,
                "workload": engine.workload_estimate(emp)}

    def file_dispute(self, emp_id: str, reason: str, actor: str) -> Dict:
        with STORE.lock:
            emp = STORE.employee(emp_id)
            emp.dispute_status, emp.dispute_note = "Pending Manager Review", reason
            STORE.ledger.record(actor, "EVIDENCE_DISPUTE_FILED", emp.id, {"reason": reason})
            return {"status": "DISPUTE_LOGGED", "employee_id": emp.id}

    def resolve_dispute(self, emp_id: str, resolution: str, note: str, actor: str) -> Dict:
        with STORE.lock:
            emp = STORE.employee(emp_id)
            if emp.dispute_status != "Pending Manager Review":
                raise HTTPException(409, "No pending dispute for this employee")
            emp.dispute_status = f"Resolved — {resolution}"
            STORE.ledger.record(actor, "EVIDENCE_DISPUTE_RESOLVED", emp.id, {"resolution": resolution, "note": note})
            return {"status": emp.dispute_status}


# =================================================================== Agent 6
class RiskPredictionAgent:
    name = "Agent 6 (Risk Prediction)"

    def classify(self, task: Task, on_critical_path: bool) -> str:
        if task.priority == "Critical" or on_critical_path:
            return "Critical"
        return "High" if task.priority == "High" else "Medium"

    def disruption(self, emp_id: str, new_status: str, leave_days: int, reason: str, actor: str) -> Dict:
        with STORE.lock:
            emp = STORE.employee(emp_id)
            before = {"status": emp.status, "leave_hrs": emp.leave_hrs}
            emp.status = new_status
            if new_status == "On Leave":
                emp.leave_hrs = min(emp.weekly_capacity_hrs, leave_days * emp.availability.working_hrs_day)
            elif new_status == "Available":
                emp.leave_hrs = 0.0
            active = [t for t in STORE.tasks if t.assigned_to == emp.id and t.status != "COMPLETED_AND_AUDITED"]
            if new_status == "On Leave":
                affected = active
            elif new_status == "Overloaded":
                affected = self._offload_set(emp, active)
            else:
                affected = []
            cp = set(engine.critical_path(STORE.tasks)["path"]) if STORE.tasks else set()
            proposals = []
            for t in sorted(affected, key=lambda x: (PRIORITY_RANK[x.priority], x.deadline_days)):
                if any(a.task_id == t.id and a.status == "PENDING" and a.kind == "REALLOCATION" for a in STORE.approvals):
                    continue  # duplicate-safe: one open reallocation per task
                risk = self.classify(t, t.id in cp)
                t.status = "AT_RISK_DISRUPTED"
                cands = engine.rank_candidates(STORE.employees, t, STORE.weights, exclude=emp.id)
                best = cands[0] if cands else None
                downstream = [x.id for x in STORE.tasks if t.id in x.dependencies]
                if best and best["eligible"]:
                    t.status = "REALLOCATION_PROPOSED"
                    text = (f"Risk Level: {risk.upper()}. {emp.name} marked {new_status} ({reason}). Agent 6 & Agent 7 evaluated downstream "
                            f"DAG impact ({', '.join(downstream) or 'no downstream tasks'}) and recommend reassigning {t.id} to {best['employee_name']} "
                            f"(Suitability: {best['suitability_score']}/100, Post-Load: {best['utilization_after_pct']}%) without breaching capacity limits.")
                    action = f"REASSIGN {t.id} -> {best['employee_id']}"
                else:
                    text = (f"Risk Level: {risk.upper()}. {emp.name} marked {new_status}. No eligible internal candidate for {t.id}: "
                            f"{'; '.join(best['hard_violations']) if best else 'no candidates'}. Escalate: extend deadline, split task or add external capacity.")
                    action = f"ESCALATE {t.id}"
                dec = _decision(self.name, f"DISRUPTION {emp.id} {new_status}", cands, action, risk, True)
                apr = ApprovalRecord(approval_id=STORE.next_id("APR"), decision_id=dec.id, kind="REALLOCATION", task_id=t.id, task_title=t.title,
                                     priority=t.priority, previous_owner=emp.name, previous_owner_id=emp.id,
                                     recommended_new_owner_id=best["employee_id"] if best and best["eligible"] else None,
                                     recommended_new_owner_name=best["employee_name"] if best and best["eligible"] else None,
                                     suitability_score=best["suitability_score"] if best else 0.0,
                                     post_utilization_pct=best["utilization_after_pct"] if best else 0.0,
                                     explanation=text, shortlist=cands[:4], created_at=utcnow())
                STORE.approvals.append(apr)
                proposals.append({**apr.model_dump(), "risk_level": risk, "downstream_tasks": downstream})
            STORE.ledger.record("AGENT_6_RISK_MONITOR", "DISRUPTION_DETECTED", emp.id,
                                {"before": before, "after": {"status": emp.status, "leave_hrs": emp.leave_hrs},
                                 "reason": reason, "affected_tasks": [t.id for t in affected], "triggered_by": actor})
            return {"agent": self.name, "disrupted_employee": emp.name, "new_status": new_status, "proposals_created": proposals,
                    "gini_now": engine.team_gini(STORE.employees)}

    @staticmethod
    def _offload_set(emp, active: List[Task]) -> List[Task]:
        """Cascade offload: shed lowest-priority tasks until utilisation <= 85%."""
        out, util = [], engine.util_pct(emp)
        for t in sorted(active, key=lambda x: (-PRIORITY_RANK[x.priority], -x.deadline_days)):
            if util <= engine.HITL_LOAD_THRESHOLD:
                break
            out.append(t)
            util -= t.estimated_hours / emp.weekly_capacity_hrs * 100
        return out

    def scan(self) -> Dict:
        risks = []
        for e in STORE.employees:
            u = engine.util_pct(e)
            if e.status == "On Leave" and any(t.assigned_to == e.id and t.status != "COMPLETED_AND_AUDITED" for t in STORE.tasks):
                risks.append({"type": "OWNER_ON_LEAVE", "level": "Critical", "entity": e.id, "detail": f"{e.name} is on leave with open tasks"})
            elif u > engine.HARD_CAPACITY_CEILING:
                risks.append({"type": "BURNOUT", "level": "Critical", "entity": e.id, "detail": f"{e.name} at {u}% utilization"})
            elif u > engine.HITL_LOAD_THRESHOLD:
                risks.append({"type": "OVERLOAD", "level": "High", "entity": e.id, "detail": f"{e.name} at {u}% utilization"})
        for p in STORE.projects:
            ptasks = [t for t in STORE.tasks if t.project_id == p.id]
            if not ptasks:
                continue
            cp = engine.critical_path(ptasks)
            days = round(cp["total_hours"] / 6.0, 1)   # ~6 focused hours/day on a sequential chain
            if days > p.deadline_days:
                risks.append({"type": "DEADLINE_INFEASIBLE", "level": "Critical", "entity": p.id,
                              "detail": f"Critical path needs ~{days} days vs {p.deadline_days}-day deadline"})
            elif days > 0.8 * p.deadline_days:
                risks.append({"type": "DEADLINE_TIGHT", "level": "Medium", "entity": p.id,
                              "detail": f"Critical path ~{days} days of {p.deadline_days} available"})
            for t in ptasks:
                if t.status in ("AT_RISK_DISRUPTED", "REALLOCATION_PROPOSED"):
                    risks.append({"type": "TASK_DISRUPTED", "level": "High", "entity": t.id, "detail": f"{t.title} awaiting reallocation"})
        for g in WorkforceIntelligenceAgent().skill_gaps()["gaps"]:
            if g["severity"] in ("Critical", "High"):
                risks.append({"type": "SKILL_GAP", "level": g["severity"], "entity": g["skill"],
                              "detail": f"{g['skill']}: {len(g['verified_holders'])} verified holder(s) for {len(g['tasks'])} task(s)"})
        order = ["Critical", "High", "Medium", "Low"]
        risks.sort(key=lambda r: order.index(r["level"]))
        return {"agent": self.name, "risks": risks}


# =================================================================== Agent 7
class CoordinationAgent:
    """Supervisor: routes natural-language requests to the other agents and gates execution (HITL)."""
    name = "Agent 7 (Coordination Supervisor)"

    def decide(self, approval_id: str, approve: bool, comments: Optional[str], actor: str) -> Dict:
        with STORE.lock:
            apr = next((a for a in STORE.approvals if a.approval_id == approval_id), None)
            if apr is None:
                raise HTTPException(404, "Approval record not found")
            if apr.status != "PENDING":
                raise HTTPException(409, f"Approval already {apr.status}")   # idempotent: no double execution
            task = STORE.task(apr.task_id)
            apr.status = "APPROVED" if approve else "REJECTED"
            apr.manager_comments, apr.decided_at, apr.decided_by = comments, utcnow(), actor
            verification: Dict = {}
            if apr.kind == "INITIAL_ALLOCATION":
                asg = next((a for a in reversed(STORE.assignments) if a.task_id == task.id and a.status == "PENDING_HITL_APPROVAL"), None)
                emp = STORE.find_employee(apr.recommended_new_owner_id)
                if approve:
                    task.status = "ASSIGNED"
                    if asg:
                        asg.status = "ACTIVE"
                else:
                    if emp and task.assigned_to == emp.id:
                        emp.committed_hrs = max(0.0, emp.committed_hrs - task.estimated_hours)
                    task.assigned_to, task.status = None, "READY_FOR_ALLOCATION"
                    if asg:
                        asg.status = "RELEASED"
                verification = {"task_status": task.status, "assigned_to": task.assigned_to,
                                "verified": (task.assigned_to == apr.recommended_new_owner_id) if approve else task.assigned_to is None}
            else:
                if approve:
                    if not apr.recommended_new_owner_id:
                        raise HTTPException(422, "Escalation records have no candidate to execute; reject and re-plan instead")
                    new_emp = STORE.employee(apr.recommended_new_owner_id)
                    check = engine.score_candidate_for_task(new_emp, task, STORE.weights)
                    if not check["eligible"]:   # state changed since the proposal: re-validate before executing
                        apr.status = "PENDING"
                        apr.decided_at = apr.decided_by = None
                        raise HTTPException(409, "Candidate no longer eligible: " + "; ".join(check["hard_violations"]))
                    prev = STORE.find_employee(apr.previous_owner_id)
                    if prev and task.assigned_to == prev.id:
                        prev.committed_hrs = max(0.0, prev.committed_hrs - task.estimated_hours)
                    for a in STORE.assignments:
                        if a.task_id == task.id and a.status in ("ACTIVE", "PENDING_HITL_APPROVAL"):
                            a.status = "RELEASED"
                    new_emp.committed_hrs += task.estimated_hours
                    task.assigned_to, task.status = new_emp.id, "ASSIGNED"
                    STORE.assignments.append(TaskAssignment(id=STORE.next_id("ASG"), task_id=task.id, employee_id=new_emp.id,
                                                            suitability_score=check["suitability_score"], factor_breakdown=check["factor_breakdown"],
                                                            explanation_rationale=apr.explanation, tradeoffs_flagged=check["warnings"], status="ACTIVE"))
                    verification = {"task_status": task.status, "assigned_to": task.assigned_to,
                                    "new_owner_utilization_pct": engine.util_pct(new_emp), "verified": task.assigned_to == new_emp.id}
                else:
                    task.status = "AT_RISK_DISRUPTED"
                    verification = {"task_status": task.status, "verified": True}
            STORE.ledger.record("PROJECT_MANAGER_HITL", "REALLOCATION_APPROVED" if approve and apr.kind == "REALLOCATION"
                                else ("ALLOCATION_APPROVED" if approve else "APPROVAL_REJECTED"), task.id,
                                {"approval_id": approval_id, "kind": apr.kind, "new_owner": apr.recommended_new_owner_id,
                                 "comments": comments, "decided_by": actor, "verification": verification})
            return {"status": "EXECUTED_AND_VERIFIED" if approve and verification.get("verified") else apr.status,
                    "approval": apr.model_dump(), "verification": verification}

    # ------------------------------------------------------------ chat router
    def chat(self, query: str, user: Dict) -> Dict:
        """Read-only fallback for the offline assistant. Changes go through assistant.propose and its approval card."""
        q = query.lower().strip()
        trace: List[str] = ["Agent 7: intent routing"]
        emp = self._find_employee(q)
        task = self._find_task(q)

        def reply(text: str, data: Optional[Dict] = None) -> Dict:
            return {"agent": self.name, "response": text, "data": data or {}, "trace": trace}

        def explain(t: Task) -> Dict:
            asg = next((a for a in reversed(STORE.assignments) if a.task_id == t.id), None)
            trace.append("Agent 3: explanation lookup")
            return reply(asg.explanation_rationale if asg else f"{t.id} has not been allocated yet.")

        def scores(e: Employee) -> Dict:
            s = engine.compute_6_scores(e)
            trace.append("Agent 5: 6-score evaluation")
            return reply(f"{e.name}: {s['level']}. Skill {s['skill_score']}, Performance {s['performance_score'] if s['performance_score'] is not None else 'withheld (insufficient evidence)'}, "
                         f"Availability {s['availability_score']}, Workload {s['workload_score']}%, Collaboration {s['collaboration_score']}.", s)

        asks_why = any(k in q for k in ("why", "explain"))
        asks_scores = any(k in q for k in ("score", "perform", "how is", "profile", "level"))
        if user["role"] != "ADMIN":   # staff see their own records; team-wide data stays behind the admin tools
            if task and asks_why and task.assigned_to == user.get("emp"):
                return explain(task)
            if emp and asks_scores:
                return scores(emp) if user.get("emp") == emp.id else reply("Staff can only view their own evaluation.")
            return reply("I can help with your own tasks, scores and requests. Team-wide workload, risks, rankings and approvals need an administrator.")
        if any(k in q for k in ("leave", "sick", "unavailable", "out of office", "absent", "emergency")):
            return reply("To report someone as unavailable, tell me who and for how long, for example “Asha is on leave for 3 days”. You will get a card to approve.")
        if "what if" in q or "what-if" in q:
            if task and emp:
                trace += ["Agent 3: counterfactual simulation"]
                r = TaskAllocationAgent().what_if(task.id, emp.id)
                return reply(f"If {emp.name} takes {task.id}: suitability {r['candidate']['suitability_score']}/100 (rank #{r['rank']}), "
                             f"post-load {r['candidate']['utilization_after_pct']}%, Gini {r['gini_before']} → {r['gini_after']}. {r['verdict']}.", r)
            return reply("Tell me both a task and a person, e.g. “What if Asha takes TSK-12?”")
        if any(k in q for k in ("who should", "best for", "best person", "recommend", "assign")) and task:
            trace += [f"Entity: {task.id}", "Engine: hard filter + weighted scoring", "Agent 3: explanation"]
            cands = engine.rank_candidates(STORE.employees, task, STORE.weights)
            top = cands[0]
            lines = [f"{i + 1}. {c['employee_name']} — {c['suitability_score']}{'' if c['eligible'] else ' (ineligible: ' + '; '.join(c['hard_violations']) + ')'}"
                     for i, c in enumerate(cands[:4])]
            return reply(f"For {task.id} ({task.title}) the best candidate is {top['employee_name']}.\n" + "\n".join(lines),
                         {"shortlist": cands[:4]})
        if any(k in q for k in ("allocate", "plan the", "run allocation")):
            return reply("To allocate tasks, say “run allocation”. You will get a card to approve first.")
        if any(k in q for k in ("fair", "gini", "overload", "workload", "burnout", "balance")):
            trace += ["Engine: utilisation + Gini"]
            utils = sorted(((e.name, engine.util_pct(e)) for e in STORE.employees if e.status != "On Leave"), key=lambda x: -x[1])
            over = [f"{n} ({u}%)" for n, u in utils if u > engine.HITL_LOAD_THRESHOLD]
            return reply(f"Team workload Gini is {engine.team_gini(STORE.employees)} (0 = perfectly even). "
                         f"Overloaded (>85%): {', '.join(over) or 'nobody'}. Most headroom: "
                         + ", ".join(f"{n} ({u}%)" for n, u in utils[-3:]) + ".", {"utilization": utils})
        if any(k in q for k in ("risk", "delay", "deadline", "late")):
            trace += ["Agent 6: risk scan"]
            r = RiskPredictionAgent().scan()
            top = r["risks"][:5]
            return reply("Top risks:\n" + ("\n".join(f"• [{x['level']}] {x['detail']}" for x in top) or "No active risks."), r)
        if any(k in q for k in ("skill gap", "gap", "training", "upskill", "learn")):
            trace += ["Agent 2: skill gap analysis"]
            r = WorkforceIntelligenceAgent().skill_gaps()
            g = [x for x in r["gaps"] if x["severity"] in ("Critical", "High")]
            return reply("Skill gaps:\n" + ("\n".join(f"• {x['skill']} ({x['severity']}): verified holders {', '.join(x['verified_holders']) or 'none'}"
                                                      for x in g) or "No critical gaps."), r)
        if any(k in q for k in ("pending", "approval", "queue")):
            pend = [a for a in STORE.approvals if a.status == "PENDING"]
            return reply(f"{len(pend)} approval(s) pending: " + (", ".join(f"{a.approval_id} ({a.task_id})" for a in pend) or "none") + ".")
        if task and asks_why:
            return explain(task)
        if emp and asks_scores:
            return scores(emp)
        if any(k in q for k in ("free", "available", "capacity", "bandwidth")) or not q:
            trace += ["Agent 2: capacity scan"]
            evals = [engine.compute_6_scores(e) for e in STORE.employees]
            avail = sorted([e for e in evals if e["status"] == "Available" and e["free_capacity_hrs"] >= 8], key=lambda x: -x["free_capacity_hrs"])
            return reply(f"{len(avail)} employees have ≥ 8h net free capacity this week. Top bandwidth: "
                         + ", ".join(f"{e['name']} ({e['free_capacity_hrs']}h, Skill {e['skill_score']})" for e in avail[:4]) + ".",
                         {"available_shortlist": avail[:5]})
        return reply("I can help with: who should do a task (“Who should do TSK-12?”), what-if simulations (“What if Asha takes TSK-12?”), "
                     "disruptions (“Asha is on leave for 3 days”), workload fairness, risks, skill gaps and pending approvals.")

    @staticmethod
    def _find_employee(q: str):
        for e in STORE.employees:
            first, full = e.name.split()[0].lower(), e.name.lower()
            if e.id.lower() in q or full in q or re.search(rf"\b{re.escape(first)}\b", q):
                return e
        return None

    @staticmethod
    def _find_task(q: str):
        m = re.search(r"tsk-?(\d+)", q)
        if m:
            return next((t for t in STORE.tasks if t.id == f"TSK-{m.group(1)}"), None)
        return None
