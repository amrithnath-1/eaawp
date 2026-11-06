"""
Project Manager action tools. Every one changes project records, so every one needs a person's approval first; the
allocation engine's own human-approval rule still applies on top (critical work and loads above 85% wait again for a
manager in Projects → Approvals). No external side effects.

  pm_create_project     MEDIUM  create a draft project (name, objective, priority, deadline)
  pm_run_allocation     MEDIUM  run the deterministic allocation for unassigned tasks (one project or all)
  pm_assign_task        MEDIUM  give one task to one person (hard constraints still enforced)
  pm_report_leave       MEDIUM  record that someone is on leave and propose reallocation of their work
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool

ROLE = ["PROJECT_MANAGER"]


class CreateProjectInput(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    objective: str = Field(default="", max_length=4000)
    priority: Literal["Critical", "High", "Medium", "Low"] = "High"
    deadline_days: int = Field(default=30, ge=3, le=730)


class AllocationInput(BaseModel):
    project_id: Optional[str] = Field(default=None, max_length=40)


class AssignInput(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=40)
    employee_id: str = Field(..., min_length=1, max_length=40)
    reason: str = Field(default="Assigned through the Project Manager AI employee", max_length=300)


class LeaveInput(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=40)
    leave_days: int = Field(default=3, ge=1, le=60)
    reason: str = Field(default="Leave", max_length=300)


class _PmAction(BaseActionTool):
    model: type[BaseModel]

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            return True, "", self.model(**arguments).model_dump()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        from app.projects.context import pm_action_context
        p = self.model(**arguments)
        try:
            async with pm_action_context(db, tenant_id, "Project Manager (AI, approved)") as ctx:
                return {"success": True, **self.run(ctx, p)}
        except HTTPException as exc:
            return {"success": False, "message": str(exc.detail)}

    def run(self, ctx, p) -> dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError


class PmCreateProjectAction(_PmAction):
    model = CreateProjectInput

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="pm_create_project", display_name="Create Draft Project",
            description="Create a DRAFT project (name, objective, priority, deadline in days). Its plan is made later from "
                        "uploaded documents and approved by a person. Requires approval.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=ROLE)

    def run(self, ctx, p):
        from app.projects import services
        project = services.create_draft_project(p.name, p.objective, p.priority, p.deadline_days, ctx.actor)
        return {"project_id": project["id"], "message": f"Draft project '{project['name']}' ({project['id']}) created. "
                                                        "Upload its brief in Projects to build the plan."}


class PmRunAllocationAction(_PmAction):
    model = AllocationInput

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="pm_run_allocation", display_name="Run Task Allocation",
            description="Allocate unassigned tasks with the deterministic engine (skill, availability, workload balance, "
                        "priority, performance, growth; leave and capacity are hard limits). Critical tasks and loads above "
                        "85% still wait for a manager. Requires approval.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=ROLE)

    def run(self, ctx, p):
        from app.projects import services
        r = services.run_allocation(ctx.actor, p.project_id)
        allocs = r.get("allocations", [])
        assigned = [a for a in allocs if a.get("status") == "ASSIGNED"]
        waiting = [a for a in allocs if a.get("status") == "PENDING_HITL_APPROVAL"]
        lines = [f"{a['task_id']} → {a['recommended']['employee_name']} ({a['recommended']['suitability_score']})" for a in allocs if a.get("recommended")]
        return {"assigned": len(assigned), "waiting_for_approval": len(waiting),
                "message": f"{len(assigned)} task(s) assigned, {len(waiting)} waiting for a manager's approval. " + "; ".join(lines[:12])}


class PmAssignTaskAction(_PmAction):
    model = AssignInput

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="pm_assign_task", display_name="Assign Task",
            description="Give one task to one team member. Refused if it breaks a hard constraint (leave, capacity, missing "
                        "critical skill). Requires approval.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=ROLE)

    def run(self, ctx, p):
        from app.projects import services
        r = services.assign_task(p.task_id, p.employee_id, p.reason, ctx.actor)
        return {"task_id": p.task_id, "message": f"{p.task_id} assigned (suitability {r['candidate']['suitability_score']})."}


class PmReportLeaveAction(_PmAction):
    model = LeaveInput

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="pm_report_leave", display_name="Record Leave & Propose Reallocation",
            description="Record that a team member is on leave; their open tasks get reallocation PROPOSALS that a manager "
                        "approves. Requires approval.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=ROLE)

    def run(self, ctx, p):
        from app.projects.agents import RiskPredictionAgent
        from app.projects.store import STORE
        r = RiskPredictionAgent().disruption(p.employee_id, "On Leave", p.leave_days, p.reason, ctx.actor)
        n = len(r.get("proposals_created", []))
        if n:
            STORE.notify("approval", f"{r['disrupted_employee']}: On Leave", f"{n} reallocation proposal(s) need approval.", audience_role="ADMIN")
        return {"proposals": n, "message": f"{r['disrupted_employee']} is on leave for {p.leave_days} day(s); {n} reallocation proposal(s) wait for approval."}
