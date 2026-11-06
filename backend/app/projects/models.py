"""Domain entities (15 core enterprise entities) and API request/response models."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SkillLevel = Literal["Beginner", "Intermediate", "Advanced", "Expert"]
Priority = Literal["Low", "Medium", "High", "Critical"]
Role = Literal["OWNER", "ADMIN", "MANAGER", "STAFF"]

# Task lifecycle (state chart, section 3.3)
TASK_STATES = [
    "DRAFT_GENERATED",
    "READY_FOR_ALLOCATION",
    "BLOCKED_BY_DEPENDENCY",
    "CANDIDATES_SCORED",
    "PENDING_HITL_APPROVAL",
    "ASSIGNED",
    "IN_PROGRESS",
    "AT_RISK_DISRUPTED",
    "REALLOCATION_PROPOSED",
    "DELIVERABLE_IN_REVIEW",
    "COMPLETED_AND_AUDITED",
]


# ---------------------------------------------------------------- entities
class EmployeeSkill(BaseModel):
    skill_name: str
    level: SkillLevel
    is_verified: bool
    evidence_source: str


class AvailabilitySchedule(BaseModel):
    timezone: str = "Asia/Kolkata"
    working_hrs_day: float = 8.0
    meeting_hrs_week: float = 0.0
    leave_hrs_week: float = 0.0


class Employee(BaseModel):
    id: str
    name: str
    email: str
    department: str
    designation: str
    manager: str
    team_role_id: str
    years_exp: float
    skills: List[EmployeeSkill]
    weekly_capacity_hrs: float = 40.0
    committed_hrs: float
    meeting_hrs: float
    leave_hrs: float = 0.0
    status: str = "Available"
    delivery_completion_rate: float
    work_quality_acceptance_rate: float
    deadline_reliability_rate: float
    collaboration_review_score: float
    learning_improvement_score: float
    preferred_tasks: List[str]
    learning_goals: List[str]
    sufficient_evidence: bool = True
    dispute_status: str = "None"
    dispute_note: Optional[str] = None
    availability: AvailabilitySchedule = Field(default_factory=AvailabilitySchedule)


class TeamRole(BaseModel):
    id: str
    name: str
    department: str
    role_eval_weights: Dict[str, float]


class Project(BaseModel):
    id: str
    name: str
    business_objective: str
    priority: Priority
    deadline_days: int
    status: str = "Active"     # Draft | Active | Completed | Archived
    created_by: str = "SYSTEM"
    start_date: Optional[str] = None
    manager_usernames: List[str] = []


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    required_skills: Dict[str, SkillLevel]
    estimated_hours: float
    priority: Priority
    deadline_days: int
    dependencies: List[str] = []
    deliverable_criteria: str
    status: str = "READY_FOR_ALLOCATION"
    assigned_to: Optional[str] = None
    progress_pct: int = 0      # employee-reported; never counted as verified progress
    phase: Optional[str] = None
    milestone: Optional[str] = None
    complexity: int = 3
    acceptance_criteria: List[str] = []
    deliverables: List[str] = []
    subtasks: List[str] = []
    suggested_assignee: Optional[str] = None
    blocked: bool = False
    blocked_reason: Optional[str] = None
    plan_id: Optional[str] = None
    activity: List[Dict] = []


class TaskDependency(BaseModel):
    task_id: str
    depends_on_task_id: str
    is_satisfied: bool


class TaskAssignment(BaseModel):
    id: str
    task_id: str
    employee_id: str
    suitability_score: float
    factor_breakdown: Dict[str, float]
    explanation_rationale: str
    tradeoffs_flagged: List[str]
    status: str  # PROPOSED | PENDING_HITL_APPROVAL | ACTIVE | RELEASED


class WorkloadEstimate(BaseModel):
    employee_id: str
    committed_hrs: float
    free_capacity_hrs: float
    utilization_pct: float
    is_overloaded: bool


class Deliverable(BaseModel):
    id: str
    task_id: str
    employee_id: str
    accepted: bool
    rework_count: int
    complexity_weight: float


class PerformanceEvaluation(BaseModel):
    employee_id: str
    skill_score: float
    performance_score: float
    availability_score: float
    workload_score: float
    collaboration_score: float
    level: str
    dispute_status: str


class IntegrationEvent(BaseModel):
    id: str
    employee_id: str
    source_system: Literal["GitHub", "Jira", "Calendar"]
    external_id: str
    pr_review_score: Optional[float] = None
    defect_rate: Optional[float] = None
    summary: str
    received_at: str


class AgentDecision(BaseModel):
    id: str
    agent_name: str
    trigger_event: str
    shortlist: List[Dict]
    recommended_action: str
    risk_level: Literal["Low", "Medium", "High", "Critical"]
    requires_approval: bool
    created_at: str


class ApprovalRecord(BaseModel):
    approval_id: str
    decision_id: str
    kind: Literal["INITIAL_ALLOCATION", "REALLOCATION"]
    task_id: str
    task_title: str
    priority: str
    previous_owner: Optional[str]
    previous_owner_id: Optional[str]
    recommended_new_owner_id: Optional[str]
    recommended_new_owner_name: Optional[str]
    suitability_score: float
    post_utilization_pct: float
    explanation: str
    shortlist: List[Dict] = []
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    manager_comments: Optional[str] = None
    created_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None


class AuditLog(BaseModel):
    id: str
    timestamp: str
    actor: str
    action: str
    entity_id: str
    details: Dict
    prev_hash: str
    sha256_proof: str


class User(BaseModel):
    username: str
    display_name: str
    role: Role
    employee_id: Optional[str] = None
    password_hash: str
    salt: str


# ---------------------------------------------------------------- requests
class WeightConfig(BaseModel):
    skill_match: float = 0.30
    availability: float = 0.20
    workload_balance: float = 0.20
    priority_alignment: float = 0.15
    past_performance: float = 0.10
    development_opportunity: float = 0.05

    @model_validator(mode="after")
    def check_sum(self):
        vals = list(self.model_dump().values())
        if any(v < 0 or v > 0.6 for v in vals):
            raise ValueError("Each weight must be between 0 and 0.6")
        if abs(sum(vals) - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0 (got {round(sum(vals), 3)})")
        return self


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    objective: str = Field(min_length=10, max_length=4000)
    priority: Priority = "High"
    deadline_days: int = Field(default=30, ge=3, le=365)


class DisruptionRequest(BaseModel):
    employee_id: str
    new_status: Literal["On Leave", "Overloaded", "Available"] = "On Leave"
    leave_days: int = Field(default=3, ge=1, le=60)
    reason: str = Field(default="Medical Emergency", max_length=300)


class DecisionRequest(BaseModel):
    comments: Optional[str] = Field(default=None, max_length=500)


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)
    employee_id: Optional[str] = None


class DisputeResolveRequest(BaseModel):
    resolution: Literal["Upheld", "Rejected"]
    note: str = Field(default="", max_length=500)


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    status: Optional[Literal["active", "archived"]] = None


class ResetRequest(BaseModel):
    confirm: Literal["RESET"]


class WhatIfRequest(BaseModel):
    task_id: str
    employee_id: str


class ProgressUpdateRequest(BaseModel):
    progress_pct: int = Field(ge=0, le=100)
    status: Optional[Literal["IN_PROGRESS", "DELIVERABLE_IN_REVIEW"]] = None


class ProjectDraftRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    objective: str = Field(default="", max_length=4000)
    priority: Priority = "High"
    deadline_days: int = Field(default=30, ge=3, le=730)


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=120)
    objective: Optional[str] = Field(default=None, max_length=4000)
    priority: Optional[Priority] = None
    deadline_days: Optional[int] = Field(default=None, ge=3, le=730)
    status: Optional[Literal["Draft", "Active", "Completed", "Archived"]] = None


class ClarificationAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class SpecUpdateRequest(BaseModel):
    summary: Optional[str] = Field(default=None, max_length=4000)
    notes: Optional[str] = Field(default=None, max_length=4000)


class PlanTask(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=1500)
    phase: str = Field(default="Build", max_length=80)
    milestone: str = Field(default="Delivery", max_length=120)
    required_skills: Dict[str, SkillLevel]
    priority: Priority = "Medium"
    estimated_hours: float = Field(gt=0, le=400)
    complexity: int = Field(default=3, ge=1, le=5)
    deadline_days: int = Field(ge=1, le=730)
    depends_on_keys: List[str] = []
    acceptance_criteria: List[str] = []
    deliverables: List[str] = []
    subtasks: List[str] = []
    suggested_assignee_id: Optional[str] = None
    suggested_assignee_name: Optional[str] = None
    suggestion_reason: Optional[str] = None


class PlanBody(BaseModel):
    summary: str = Field(default="", max_length=4000)
    tasks: List[PlanTask] = Field(min_length=1, max_length=80)
    risks: List[str] = []
    resource_gaps: List[str] = []
    phases: List[str] = []
    milestones: List[Dict] = []


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=1500)
    required_skills: Dict[str, SkillLevel] = Field(min_length=1)
    estimated_hours: float = Field(gt=0, le=400)
    priority: Priority = "Medium"
    deadline_days: int = Field(default=14, ge=1, le=730)
    dependencies: List[str] = []
    phase: Optional[str] = None
    milestone: Optional[str] = None
    acceptance_criteria: List[str] = []
    deliverables: List[str] = []


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1500)
    priority: Optional[Priority] = None
    deadline_days: Optional[int] = Field(default=None, ge=1, le=730)
    estimated_hours: Optional[float] = Field(default=None, gt=0, le=400)
    blocked: Optional[bool] = None
    blocked_reason: Optional[str] = Field(default=None, max_length=300)
    acceptance_criteria: Optional[List[str]] = None
    deliverables: Optional[List[str]] = None


class TaskAssignRequest(BaseModel):
    employee_id: str
    reason: str = Field(default="Assigned by manager", max_length=300)


class ReworkRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProgressReportRequest(BaseModel):
    reported_pct: float = Field(ge=0, le=100)
    note: str = Field(default="", max_length=1000)


EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class EmployeeCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    email: str = Field(pattern=EMAIL_RE, max_length=120)
    department: str = Field(min_length=2, max_length=60)
    designation: str = Field(min_length=2, max_length=80)
    manager: str = Field(default="", max_length=80)
    years_exp: float = Field(default=0, ge=0, le=60)
    weekly_capacity_hrs: float = Field(default=40, gt=0, le=60)
    meeting_hrs: float = Field(default=0, ge=0, le=40)
    skills: List[EmployeeSkill] = []


class EmployeeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=80)
    email: Optional[str] = Field(default=None, pattern=EMAIL_RE, max_length=120)
    department: Optional[str] = Field(default=None, min_length=2, max_length=60)
    designation: Optional[str] = Field(default=None, min_length=2, max_length=80)
    manager: Optional[str] = Field(default=None, max_length=80)
    years_exp: Optional[float] = Field(default=None, ge=0, le=60)
    weekly_capacity_hrs: Optional[float] = Field(default=None, gt=0, le=60)
    meeting_hrs: Optional[float] = Field(default=None, ge=0, le=40)
    skills: Optional[List[EmployeeSkill]] = None


class ProfileUpdateRequest(BaseModel):
    bio: str = Field(default="", max_length=1500)
    education: List[str] = []
    certifications: List[str] = []
    previous_projects: List[str] = []
    portfolio_urls: List[str] = []


class ProfessionalLinkRequest(BaseModel):
    provider: Literal["github", "linkedin", "instagram", "x", "other"]
    value: str = Field(min_length=2, max_length=300)


class SkillChallengeRequest(BaseModel):
    skill: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=1000)


class ChallengeResolveRequest(BaseModel):
    resolution: Literal["Reevaluated", "Rejected"]
    note: str = Field(default="", max_length=500)


class ChangeRequestCreate(BaseModel):
    kind: Literal["reassignment", "deadline_change", "leave"]
    task_id: Optional[str] = None
    details: str = Field(min_length=3, max_length=1000)


class ChangeRequestResolve(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)
    new_deadline_days: Optional[int] = Field(default=None, ge=1, le=730)
    leave_days: int = Field(default=3, ge=1, le=60)


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None


class IntegrationEventRequest(BaseModel):
    employee_id: str
    source_system: Literal["GitHub", "Jira", "Calendar"]
    external_id: str = Field(min_length=1, max_length=120)
    pr_review_score: Optional[float] = Field(default=None, ge=0, le=100)
    defect_rate: Optional[float] = Field(default=None, ge=0, le=100)
    meeting_hrs_delta: Optional[float] = Field(default=None, ge=-40, le=40)
    summary: str = Field(max_length=500)

    @field_validator("summary")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()
