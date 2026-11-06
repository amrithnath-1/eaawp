"""Administrator-controlled skill scores, with history, and employee requests to review them."""
from typing import Dict, List, Optional

from fastapi import HTTPException

from .audit import utcnow
from .models import EmployeeSkill
from .store import STORE

# 0-10 scale. The label is what the number means; it says nothing about workload, availability or delivery.
SCALE = {0: "No demonstrated ability", 1: "Awareness", 3: "Beginner: works with guidance", 5: "Intermediate: works independently on routine tasks",
         7: "Advanced: handles complex work", 9: "Expert: sets direction for others"}
KINDS = ("add", "correct", "reassess", "recognize_work", "qualification")
STATUSES = ("pending", "under_review", "approved", "rejected", "more_information")
CONFIDENCE = ("low", "medium", "high")


def level_for_score(score: float) -> str:
    if score >= 9:
        return "Expert"
    if score >= 7:
        return "Advanced"
    if score >= 5:
        return "Intermediate"
    return "Beginner"


def set_score(employee_id: str, skill: str, score: float, confidence: str, reason: str, evidence: Optional[str], evaluator: str, source_request: Optional[str] = None) -> Dict:
    """Every change is a new row, so earlier assessments stay visible. Only this path changes a skill record."""
    name = skill.strip()
    if not name:
        raise HTTPException(422, "Enter the skill name")
    if not 0 <= score <= 10:
        raise HTTPException(422, "Skill scores run from 0 to 10")
    if confidence not in CONFIDENCE:
        raise HTTPException(422, "Evidence confidence must be low, medium or high")
    if not reason.strip():
        raise HTTPException(422, "Record the reason for this score")
    with STORE.lock:
        emp = STORE.employee(employee_id)
        record_id = STORE.next_id("SKM")
        now = utcnow()
        STORE.add("skill_manual_scores", {"id": record_id, "employee_id": employee_id, "skill": name, "score": score, "confidence": confidence,
                                          "reason": reason.strip(), "evidence": evidence, "evaluator": evaluator, "evaluated_at": now,
                                          "source_request": source_request})
        emp.skills = [s for s in emp.skills if s.skill_name.lower() != name.lower()]
        if score >= 1:      # below that the person has no demonstrated ability, so it must not count for allocation
            emp.skills.append(EmployeeSkill(skill_name=name, level=level_for_score(score), is_verified=True, evidence_source=f"Assessed by {evaluator}"))
        STORE.ledger.record(evaluator, "SKILL_SCORE_SET", employee_id, {"skill": name, "score": score, "confidence": confidence, "reason": reason.strip(), "request": source_request})
    return {"id": record_id, "employee_id": employee_id, "skill": name, "score": score, "confidence": confidence, "reason": reason.strip(), "evidence": evidence, "evaluator": evaluator, "evaluated_at": now}


def history(employee_id: str, skill: Optional[str] = None) -> List[Dict]:
    STORE.employee(employee_id)
    rows = sorted([dict(r) for r in STORE.rows("skill_manual_scores", employee_id=employee_id)], key=lambda r: (r["evaluated_at"], r["id"]), reverse=True)
    return [r for r in rows if not skill or r["skill"].lower() == skill.lower()]


def submit(employee_id: str, skill: str, kind: str, requested_score: Optional[float], explanation: str, evidence: Optional[str], actor: str) -> Dict:
    if kind not in KINDS:
        raise HTTPException(422, f"Request type must be one of {', '.join(KINDS)}")
    if requested_score is not None and not 0 <= requested_score <= 10:
        raise HTTPException(422, "Skill scores run from 0 to 10")
    if not skill.strip() or not explanation.strip():
        raise HTTPException(422, "Enter the skill and an explanation")
    emp = STORE.employee(employee_id)
    request_id = STORE.next_id("SRQ")
    STORE.add("skill_requests", {"id": request_id, "employee_id": employee_id, "skill": skill.strip(), "kind": kind,
                                 "requested_score": requested_score, "explanation": explanation.strip(), "evidence": evidence,
                                 "status": "pending", "reviewer": None, "review_notes": None, "reviewed_at": None})
    STORE.ledger.record(actor, "SKILL_REQUEST_SUBMITTED", employee_id, {"request": request_id, "skill": skill.strip(), "kind": kind})
    STORE.notify("skill_request", f"Skill request: {skill.strip()}", f"{emp.name} asked for a {kind.replace('_', ' ')} review.", audience_role="ADMIN")
    return get(request_id)


def get(request_id: str) -> Dict:
    row = STORE.one("skill_requests", id=request_id)
    if not row:
        raise HTTPException(404, "Request not found")
    return dict(row)


def list_requests(user: Dict, status: Optional[str] = None) -> List[Dict]:
    rows = list(STORE.records["skill_requests"]) if user["role"] == "ADMIN" else STORE.rows("skill_requests", employee_id=user.get("emp"))
    rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)
    named = {e.id: e.name for e in STORE.employees}
    return [{**r, "employee_name": named.get(r["employee_id"], r["employee_id"])} for r in rows if not status or r["status"] == status]


def pending_count() -> int:
    return sum(1 for r in STORE.records["skill_requests"] if r["status"] in ("pending", "under_review"))


def review(request_id: str, status: str, notes: str, score: Optional[float], confidence: str, reviewer: str) -> Dict:
    """Submitting a request changes nothing. Only an administrator's approval here updates the skill."""
    if status not in STATUSES or status == "pending":
        raise HTTPException(422, "Choose under review, approved, rejected or more information")
    row = get(request_id)
    if row["status"] in ("approved", "rejected"):
        raise HTTPException(409, f"This request was already {row['status']}")
    if status in ("rejected", "more_information") and not notes.strip():
        raise HTTPException(422, "Add a note explaining this decision")
    if status == "approved":
        final = score if score is not None else row["requested_score"]
        if final is None:
            raise HTTPException(422, "Approving needs a score from 0 to 10")
        set_score(row["employee_id"], row["skill"], final, confidence, notes.strip() or row["explanation"], row["evidence"], reviewer, request_id)
    STORE.one("skill_requests", id=request_id).update(status=status, reviewer=reviewer, review_notes=notes.strip(), reviewed_at=utcnow())
    STORE.ledger.record(reviewer, "SKILL_REQUEST_REVIEWED", row["employee_id"], {"request": request_id, "status": status})
    STORE.notify("skill_request", f"Skill request: {status.replace('_', ' ')}", f"{row['skill']}: {notes.strip() or 'No note'}", audience_employee=row["employee_id"])
    return get(request_id)


def respond(request_id: str, employee_id: Optional[str], explanation: str, evidence: Optional[str], actor: str) -> Dict:
    row = get(request_id)
    if row["employee_id"] != employee_id:
        raise HTTPException(404, "Request not found")
    if row["status"] != "more_information":
        raise HTTPException(409, "This request is not waiting for more information")
    live = STORE.one("skill_requests", id=request_id)
    live.update(status="pending", explanation=explanation.strip(), evidence=evidence if evidence is not None else live["evidence"])
    STORE.ledger.record(actor, "SKILL_REQUEST_UPDATED", employee_id, {"request": request_id})
    STORE.notify("skill_request", f"Skill request updated: {row['skill']}", "The employee added more information.", audience_role="ADMIN")
    return get(request_id)
