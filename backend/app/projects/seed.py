"""Reference simulation data from Vyuham (12 employees, 8 CRM tasks, roles, evidence). Used by the tests to verify
the reference allocation; it is never loaded into a company automatically."""
from datetime import date
from typing import List

from .models import (AvailabilitySchedule, Deliverable, Employee, EmployeeSkill as Sk, IntegrationEvent, Project,
                     Task, TeamRole, User)

def _emp(**kw) -> Employee:
    first = kw["name"].split()[0].lower()
    kw.setdefault("email", f"{first}@vyuham.demo")
    kw["availability"] = AvailabilitySchedule(meeting_hrs_week=kw["meeting_hrs"], leave_hrs_week=kw.get("leave_hrs", 0.0))
    return Employee(**kw)


def seed_employees() -> List[Employee]:
    return [
        _emp(id="EMP-01", name="Vikram Rao", department="Engineering", designation="Staff Backend Architect", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=8.5,
             skills=[Sk(skill_name="Python", level="Expert", is_verified=True, evidence_source="GitHub: 42 PRs, 99.2% test pass"),
                     Sk(skill_name="FastAPI", level="Expert", is_verified=True, evidence_source="GitHub: Core API Gateway owner"),
                     Sk(skill_name="PostgreSQL", level="Advanced", is_verified=True, evidence_source="DB Migration Lead")],
             committed_hrs=18, meeting_hrs=4, delivery_completion_rate=96, work_quality_acceptance_rate=95, deadline_reliability_rate=94,
             collaboration_review_score=92, learning_improvement_score=88, preferred_tasks=["FastAPI", "Architecture"], learning_goals=["Rust"]),
        _emp(id="EMP-02", name="Ananya Sharma", department="Engineering", designation="Senior Backend & ML Engineer", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=5.5,
             skills=[Sk(skill_name="Python", level="Expert", is_verified=True, evidence_source="GitHub: 31 PRs merged"),
                     Sk(skill_name="FastAPI", level="Advanced", is_verified=True, evidence_source="GitHub: Auth & Payment Microservice"),
                     Sk(skill_name="Machine Learning", level="Advanced", is_verified=True, evidence_source="Lead Scoring Model v2")],
             committed_hrs=18, meeting_hrs=4, delivery_completion_rate=92, work_quality_acceptance_rate=91, deadline_reliability_rate=90,
             collaboration_review_score=89, learning_improvement_score=94, preferred_tasks=["FastAPI", "Machine Learning"], learning_goals=["Kubernetes"]),
        _emp(id="EMP-03", name="Priya Nair", department="Engineering", designation="Senior Database & Backend Dev", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=6.0,
             skills=[Sk(skill_name="PostgreSQL", level="Expert", is_verified=True, evidence_source="Schema & Query Optimizer Lead"),
                     Sk(skill_name="Python", level="Advanced", is_verified=True, evidence_source="Backend Services"),
                     Sk(skill_name="Redis", level="Advanced", is_verified=True, evidence_source="Caching Layer")],
             committed_hrs=20, meeting_hrs=4, delivery_completion_rate=91, work_quality_acceptance_rate=93, deadline_reliability_rate=89,
             collaboration_review_score=86, learning_improvement_score=85, preferred_tasks=["PostgreSQL", "Redis"], learning_goals=["GraphQL"]),
        _emp(id="EMP-04", name="Rohan Verma", department="Engineering", designation="Backend Developer II", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=2.5,
             skills=[Sk(skill_name="Python", level="Intermediate", is_verified=True, evidence_source="GitHub: 14 PRs merged"),
                     Sk(skill_name="FastAPI", level="Intermediate", is_verified=True, evidence_source="Internal CRUD APIs"),
                     Sk(skill_name="Tech Writing", level="Advanced", is_verified=True, evidence_source="OpenAPI Docs")],
             committed_hrs=12, meeting_hrs=3, delivery_completion_rate=82, work_quality_acceptance_rate=84, deadline_reliability_rate=86,
             collaboration_review_score=80, learning_improvement_score=92, preferred_tasks=["FastAPI", "Python"], learning_goals=["PostgreSQL", "FastAPI"]),
        _emp(id="EMP-05", name="Karthik Iyer", department="Design & Web", designation="Lead UI/UX & Frontend Architect", manager="Meera Krishnan", team_role_id="ROLE-DES", years_exp=7.0,
             skills=[Sk(skill_name="React", level="Expert", is_verified=True, evidence_source="Design System Owner"),
                     Sk(skill_name="TypeScript", level="Expert", is_verified=True, evidence_source="Frontend Monorepo"),
                     Sk(skill_name="UI/UX Design", level="Advanced", is_verified=True, evidence_source="Figma Enterprise Kit")],
             committed_hrs=18, meeting_hrs=4, delivery_completion_rate=94, work_quality_acceptance_rate=92, deadline_reliability_rate=91,
             collaboration_review_score=95, learning_improvement_score=87, preferred_tasks=["React", "UI/UX Design"], learning_goals=["WebGL"]),
        _emp(id="EMP-06", name="Sneha Patel", department="Design & Web", designation="Senior Product Designer", manager="Meera Krishnan", team_role_id="ROLE-DES", years_exp=5.0,
             skills=[Sk(skill_name="UI/UX Design", level="Expert", is_verified=True, evidence_source="12 Validated User Flows"),
                     Sk(skill_name="Figma", level="Expert", is_verified=True, evidence_source="Component Tokens"),
                     Sk(skill_name="Requirements Analysis", level="Advanced", is_verified=True, evidence_source="PRD Co-Author")],
             committed_hrs=14, meeting_hrs=4, delivery_completion_rate=90, work_quality_acceptance_rate=94, deadline_reliability_rate=92,
             collaboration_review_score=91, learning_improvement_score=86, preferred_tasks=["UI/UX Design", "Requirements Analysis"], learning_goals=["React"]),
        _emp(id="EMP-07", name="Arjun Mehta", department="Design & Web", designation="Frontend Engineer II", manager="Meera Krishnan", team_role_id="ROLE-DES", years_exp=3.0,
             skills=[Sk(skill_name="React", level="Advanced", is_verified=True, evidence_source="Dashboard Widgets"),
                     Sk(skill_name="TypeScript", level="Intermediate", is_verified=True, evidence_source="Typed Hooks"),
                     Sk(skill_name="TailwindCSS", level="Advanced", is_verified=False, evidence_source="Self-reported")],
             committed_hrs=14, meeting_hrs=3, delivery_completion_rate=85, work_quality_acceptance_rate=83, deadline_reliability_rate=84,
             collaboration_review_score=82, learning_improvement_score=90, preferred_tasks=["React", "TypeScript"], learning_goals=["TypeScript", "Next.js"]),
        _emp(id="EMP-08", name="Divya Menon", department="Product & QA", designation="Lead Business Analyst", manager="Suresh Babu", team_role_id="ROLE-PQA", years_exp=6.5,
             skills=[Sk(skill_name="Requirements Analysis", level="Expert", is_verified=True, evidence_source="20+ Enterprise PRDs"),
                     Sk(skill_name="Tech Writing", level="Expert", is_verified=True, evidence_source="ISO Compliance Docs"),
                     Sk(skill_name="SQL", level="Intermediate", is_verified=True, evidence_source="BI Reporting")],
             committed_hrs=16, meeting_hrs=6, delivery_completion_rate=93, work_quality_acceptance_rate=95, deadline_reliability_rate=96,
             collaboration_review_score=94, learning_improvement_score=84, preferred_tasks=["Requirements Analysis", "Tech Writing"], learning_goals=["Product Analytics"]),
        _emp(id="EMP-09", name="Nikhil Joshi", department="Product & QA", designation="Senior QA Automation Engineer", manager="Suresh Babu", team_role_id="ROLE-PQA", years_exp=5.0,
             skills=[Sk(skill_name="QA Automation", level="Expert", is_verified=True, evidence_source="Playwright + Pytest Suite"),
                     Sk(skill_name="Security Testing", level="Advanced", is_verified=True, evidence_source="OWASP Audit Lead"),
                     Sk(skill_name="Python", level="Intermediate", is_verified=True, evidence_source="Test Harnesses")],
             committed_hrs=15, meeting_hrs=3, delivery_completion_rate=91, work_quality_acceptance_rate=94, deadline_reliability_rate=93,
             collaboration_review_score=88, learning_improvement_score=86, preferred_tasks=["QA Automation", "Security Testing"], learning_goals=["Chaos Engineering"]),
        _emp(id="EMP-10", name="Siddharth Rao", department="Cloud & DevOps", designation="Principal DevOps & SRE", manager="Anil Menon", team_role_id="ROLE-OPS", years_exp=7.5,
             skills=[Sk(skill_name="Docker & Kubernetes", level="Expert", is_verified=True, evidence_source="Production EKS Clusters"),
                     Sk(skill_name="CI/CD Pipelines", level="Expert", is_verified=True, evidence_source="GitHub Actions Zero-Downtime"),
                     Sk(skill_name="Cloud Security", level="Advanced", is_verified=True, evidence_source="SOC2 Infra Lead")],
             committed_hrs=20, meeting_hrs=4, delivery_completion_rate=95, work_quality_acceptance_rate=96, deadline_reliability_rate=94,
             collaboration_review_score=90, learning_improvement_score=88, preferred_tasks=["Docker & Kubernetes", "CI/CD Pipelines"], learning_goals=["Service Mesh"]),
        _emp(id="EMP-11", name="Meera Reddy", department="Engineering", designation="Full-Stack Developer", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=4.5,
             skills=[Sk(skill_name="Python", level="Advanced", is_verified=True, evidence_source="Backend Services"),
                     Sk(skill_name="React", level="Advanced", is_verified=True, evidence_source="Client Portal")],
             committed_hrs=35, meeting_hrs=4, status="Overloaded", delivery_completion_rate=89, work_quality_acceptance_rate=88, deadline_reliability_rate=85,
             collaboration_review_score=87, learning_improvement_score=84, preferred_tasks=["Python", "React"], learning_goals=["Rust"]),
        _emp(id="EMP-12", name="Kabir Das", department="Engineering", designation="Junior Trainee Engineer", manager="Anil Menon", team_role_id="ROLE-ENG", years_exp=0.4,
             skills=[Sk(skill_name="Python", level="Beginner", is_verified=False, evidence_source="Onboarding Bootcamp"),
                     Sk(skill_name="Tech Writing", level="Intermediate", is_verified=True, evidence_source="Internal Wiki")],
             committed_hrs=8, meeting_hrs=2, delivery_completion_rate=75, work_quality_acceptance_rate=78, deadline_reliability_rate=80,
             collaboration_review_score=76, learning_improvement_score=95, preferred_tasks=["Python", "Tech Writing"], learning_goals=["Python", "QA Automation"],
             sufficient_evidence=False),
    ]


def seed_projects() -> List[Project]:
    return [Project(id="PRJ-CRM", name="Enterprise CRM Platform", priority="Critical", deadline_days=30, start_date=date.today().isoformat(),
                    business_objective="Launch a multi-tenant CRM with AI lead scoring for 40 enterprise sales teams within 30 days.")]


SEED_PLAN = {"TSK-101": ("Discovery", "Requirements signed off"), "TSK-102": ("Design", "Architecture ready"), "TSK-103": ("Design", "Architecture ready"),
             "TSK-104": ("Build", "Core platform ready"), "TSK-105": ("Build", "Core platform ready"), "TSK-106": ("Build", "Core platform ready"),
             "TSK-107": ("Verification", "Release candidate verified"), "TSK-108": ("Release", "Production launch")}


def seed_tasks() -> List[Task]:
    tasks = _seed_tasks()
    for t in tasks:
        t.phase, t.milestone = SEED_PLAN[t.id]
        t.acceptance_criteria = [t.deliverable_criteria]
        t.deliverables = [t.deliverable_criteria]
    return tasks


def _seed_tasks() -> List[Task]:
    return [
        Task(id="TSK-101", project_id="PRJ-CRM", title="CRM Requirements & Domain Modeling", description="Define enterprise CRM entities, RBAC scopes, and SLA specs",
             required_skills={"Requirements Analysis": "Advanced"}, estimated_hours=10, priority="High", deadline_days=4, deliverable_criteria="Approved PRD + Domain Schema"),
        Task(id="TSK-102", project_id="PRJ-CRM", title="PostgreSQL Multi-Tenant Schema & Indexing", description="Design normalized CRM tables, row-level security, and index tuning",
             required_skills={"PostgreSQL": "Advanced", "Python": "Intermediate"}, estimated_hours=12, priority="Critical", deadline_days=8, dependencies=["TSK-101"],
             deliverable_criteria="Migration SQL + Benchmark < 10ms"),
        Task(id="TSK-103", project_id="PRJ-CRM", title="Design System & Interactive CRM Wireframes", description="High-fidelity Figma prototypes for Pipeline, Contacts, and Analytics",
             required_skills={"UI/UX Design": "Advanced"}, estimated_hours=12, priority="High", deadline_days=9, dependencies=["TSK-101"], deliverable_criteria="Figma Prototype + Token Spec"),
        Task(id="TSK-104", project_id="PRJ-CRM", title="Core CRM REST & GraphQL API Gateway", description="High-throughput FastAPI endpoints for Lead, Deal, and Auth workflows",
             required_skills={"FastAPI": "Advanced", "Python": "Advanced"}, estimated_hours=14, priority="Critical", deadline_days=15, dependencies=["TSK-102"],
             deliverable_criteria="OpenAPI Spec + 95% Unit Coverage"),
        Task(id="TSK-105", project_id="PRJ-CRM", title="AI Lead Scoring & Churn Prediction Service", description="Expose ML inference endpoint integrated with CRM deal pipeline",
             required_skills={"Machine Learning": "Advanced", "Python": "Advanced"}, estimated_hours=12, priority="High", deadline_days=18, dependencies=["TSK-102"],
             deliverable_criteria="Model Service + AUC > 0.88"),
        Task(id="TSK-106", project_id="PRJ-CRM", title="Frontend Kanban Pipeline & Analytics UI", description="React + TypeScript interactive deal board with real-time WebSockets",
             required_skills={"React": "Advanced", "TypeScript": "Intermediate"}, estimated_hours=16, priority="High", deadline_days=21, dependencies=["TSK-103", "TSK-104"],
             deliverable_criteria="Responsive SPA + Lighthouse > 92"),
        Task(id="TSK-107", project_id="PRJ-CRM", title="E2E Playwright & OWASP Security Test Suite", description="Automated regression, load testing, and RBAC penetration testing",
             required_skills={"QA Automation": "Advanced", "Security Testing": "Intermediate"}, estimated_hours=14, priority="Critical", deadline_days=26,
             dependencies=["TSK-104", "TSK-106"], deliverable_criteria="Zero Critical Vulnerabilities"),
        Task(id="TSK-108", project_id="PRJ-CRM", title="Production Kubernetes & CI/CD Deployment", description="Blue-green deployment pipeline, Prometheus alerts, and API docs",
             required_skills={"Docker & Kubernetes": "Advanced", "CI/CD Pipelines": "Advanced"}, estimated_hours=12, priority="High", deadline_days=29, dependencies=["TSK-107"],
             deliverable_criteria="Live Production URL + Runbook"),
    ]


def seed_roles() -> List[TeamRole]:
    base = {"delivery": 0.25, "quality": 0.25, "skill": 0.20, "reliability": 0.15, "collaboration": 0.10, "improvement": 0.05}
    return [
        TeamRole(id="ROLE-ENG", name="Engineering", department="Engineering", role_eval_weights=base),
        TeamRole(id="ROLE-DES", name="Design & Web", department="Design & Web", role_eval_weights=base),
        TeamRole(id="ROLE-PQA", name="Product & QA", department="Product & QA", role_eval_weights=base),
        TeamRole(id="ROLE-OPS", name="Cloud & DevOps", department="Cloud & DevOps", role_eval_weights=base),
    ]


def seed_deliverables() -> List[Deliverable]:
    rows = [("EMP-01", True, 0, 1.4), ("EMP-01", True, 1, 1.2), ("EMP-02", True, 0, 1.3), ("EMP-03", True, 0, 1.2),
            ("EMP-04", True, 2, 1.0), ("EMP-05", True, 0, 1.3), ("EMP-06", True, 0, 1.1), ("EMP-07", False, 1, 1.0),
            ("EMP-08", True, 0, 1.1), ("EMP-09", True, 0, 1.2), ("EMP-10", True, 0, 1.4), ("EMP-11", True, 1, 1.1)]
    return [Deliverable(id=f"DLV-{i + 301}", task_id=f"HIST-{i + 1:02d}", employee_id=e, accepted=a, rework_count=r, complexity_weight=c)
            for i, (e, a, r, c) in enumerate(rows)]


def seed_integration_events() -> List[IntegrationEvent]:
    ts = "2026-10-29T09:00:00Z"
    return [
        IntegrationEvent(id="INT-1", employee_id="EMP-01", source_system="GitHub", external_id="gh-pr-4182", pr_review_score=94, defect_rate=1.2,
                         summary="Merged PR #4182 API gateway rate limiter; 3 reviews, 0 post-merge defects", received_at=ts),
        IntegrationEvent(id="INT-2", employee_id="EMP-09", source_system="GitHub", external_id="gh-pr-4190", pr_review_score=91, defect_rate=0.8,
                         summary="Reviewed 6 PRs with actionable comments that were adopted", received_at=ts),
        IntegrationEvent(id="INT-3", employee_id="EMP-05", source_system="Jira", external_id="jira-DS-221", pr_review_score=None, defect_rate=2.0,
                         summary="DS-221 design tokens accepted on first review", received_at=ts),
    ]
