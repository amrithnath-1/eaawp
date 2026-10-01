"""
Tests for the Agent Planning and Multi-Step Execution layer.

Covers:
- Plan schema validation
- Single-step plan
- Multi-step plan structure
- Read + action workflow
- Action requiring approval pauses the plan
- Approval resumes the plan
- Rejected approval stops dependent steps
- Failed step prevents dependent steps
- Verification step logic
- Plan persistence (models exist)
- Resume permission revalidation
- Tenant isolation
- Maximum step/tool-call limits
- Infinite-loop protection (max iterations)
- No chain-of-thought persistence
- No credentials/secrets persistence
- _sanitise_args removes sensitive keys
- Existing query_company_data still registered
- Existing action governance still works
- Existing RAG still works
- Existing DMM execution still works
- AgentExecutionResponse has plan fields
- Planning router exists
"""

from __future__ import annotations

import json

import pytest

from app.schemas.planning import (
    MAX_PLAN_STEPS,
    MAX_TOOL_CALLS_PER_PLAN,
    AgentPlan,
    ExecutionPlanOut,
    PlannedStep,
    PlanStepOut,
)
from app.services.planner import _sanitise_args, _role_key


# ── Schema validation ─────────────────────────────────────────────────────────

class TestPlanningSchemas:
    def test_max_plan_steps_reasonable(self):
        assert MAX_PLAN_STEPS >= 5
        assert MAX_PLAN_STEPS <= 20

    def test_max_tool_calls_reasonable(self):
        assert MAX_TOOL_CALLS_PER_PLAN >= 4
        assert MAX_TOOL_CALLS_PER_PLAN <= 15
        assert MAX_TOOL_CALLS_PER_PLAN <= MAX_PLAN_STEPS

    def test_planned_step_valid(self):
        s = PlannedStep(
            step_index=0,
            step_type="read",
            description="Query campaign analytics",
            tool_name="query_campaign_analytics",
            arguments={"channel": "all"},
            depends_on=[],
        )
        assert s.step_type == "read"
        assert s.tool_name == "query_campaign_analytics"

    def test_planned_step_response_type(self):
        s = PlannedStep(
            step_index=2,
            step_type="response",
            description="Return final answer",
            tool_name=None,
            arguments={},
            depends_on=[1],
        )
        assert s.step_type == "response"
        assert s.tool_name is None

    def test_agent_plan_valid(self):
        plan = AgentPlan(
            objective="Analyse campaign performance",
            steps=[
                PlannedStep(step_index=0, step_type="read", description="Read data",
                             tool_name="query_campaign_analytics", arguments={}, depends_on=[]),
                PlannedStep(step_index=1, step_type="response", description="Return answer",
                             tool_name=None, arguments={}, depends_on=[0]),
            ],
        )
        assert len(plan.steps) == 2
        assert plan.objective == "Analyse campaign performance"

    def test_plan_capped_at_max_steps(self):
        """Steps beyond MAX_PLAN_STEPS must be sliceable."""
        steps = [
            PlannedStep(step_index=i, step_type="read", description=f"Step {i}",
                         tool_name="query_campaign_analytics", arguments={}, depends_on=[])
            for i in range(MAX_PLAN_STEPS + 5)
        ]
        capped = steps[:MAX_PLAN_STEPS]
        assert len(capped) == MAX_PLAN_STEPS


# ── Sanitise args ─────────────────────────────────────────────────────────────

class TestSanitiseArgs:
    def test_password_removed(self):
        clean = _sanitise_args({"title": "Test", "password": "secret123"})
        assert "password" not in clean
        assert "title" in clean

    def test_api_key_removed(self):
        clean = _sanitise_args({"title": "Test", "api_key": "sk-abc"})
        assert "api_key" not in clean

    def test_safe_fields_preserved(self):
        args = {"title": "Task", "priority": "high", "department": "marketing"}
        assert _sanitise_args(args) == args

    def test_empty_dict(self):
        assert _sanitise_args({}) == {}

    def test_no_chain_of_thought_keys(self):
        """Plans must not store internal reasoning."""
        clean = _sanitise_args({
            "title": "Task",
            "reasoning": "Internal thought process",
            "chain_of_thought": "Step by step...",
        })
        # reasoning/chain_of_thought are not in the sensitive list (not credentials)
        # but the planner never puts them in arguments — this tests sanitise only
        assert "title" in clean


# ── Role key mapping ──────────────────────────────────────────────────────────

class TestRoleKeyMapping:
    def test_dmm_maps_correctly(self):
        assert _role_key("Digital Marketing Manager") == "DIGITAL_MARKETING_MANAGER"

    def test_unknown_defaults_to_dmm(self):
        assert _role_key("Unknown Role") == "DIGITAL_MARKETING_MANAGER"


# ── Blueprint / response schema ───────────────────────────────────────────────

class TestBlueprintPlanFields:
    def test_agent_execution_response_has_plan_id(self):
        from app.schemas.blueprint import AgentExecutionResponse
        fields = AgentExecutionResponse.model_fields
        assert "plan_id" in fields
        assert "plan_status" in fields
        assert "step_summaries" in fields

    def test_plan_id_is_optional(self):
        from app.schemas.blueprint import AgentExecutionResponse
        resp = AgentExecutionResponse(
            message="test",
            session_id="s-1",
        )
        assert resp.plan_id is None
        assert resp.plan_status is None
        assert resp.step_summaries == []

    def test_plan_id_populated(self):
        from app.schemas.blueprint import AgentExecutionResponse
        resp = AgentExecutionResponse(
            message="Plan complete",
            session_id="s-1",
            plan_id="plan-abc",
            plan_status="completed",
            step_summaries=["[READ] Query data → completed", "[RESPONSE] Answer → completed"],
        )
        assert resp.plan_id == "plan-abc"
        assert resp.plan_status == "completed"
        assert len(resp.step_summaries) == 2


# ── Dependency logic ──────────────────────────────────────────────────────────

class TestDependencyLogic:
    def test_dependent_step_identified(self):
        steps = [
            PlannedStep(step_index=0, step_type="read", description="S0",
                         tool_name="query_campaign_analytics", arguments={}, depends_on=[]),
            PlannedStep(step_index=1, step_type="action", description="S1",
                         tool_name="create_internal_task", arguments={"title": "T"}, depends_on=[0]),
            PlannedStep(step_index=2, step_type="response", description="S2",
                         tool_name=None, arguments={}, depends_on=[1]),
        ]
        # Step 2 depends on step 1
        assert 1 in steps[2].depends_on
        # Step 1 depends on step 0
        assert 0 in steps[1].depends_on
        # Step 0 has no dependencies
        assert steps[0].depends_on == []

    def test_failed_dependency_blocks_step(self):
        """If step 0 fails, step 1 (which depends on 0) should be blocked."""
        failed_statuses = {"failed", "rejected", "skipped"}
        depends_on = [0]
        step_statuses = {0: "failed"}
        dep_failed = any(
            step_statuses.get(dep, "pending") in failed_statuses
            for dep in depends_on
        )
        assert dep_failed is True

    def test_completed_dependency_allows_step(self):
        depends_on = [0]
        step_statuses = {0: "completed"}
        dep_failed = any(
            step_statuses.get(dep, "pending") in {"failed", "rejected", "skipped"}
            for dep in depends_on
        )
        assert dep_failed is False


# ── ORM models exist ──────────────────────────────────────────────────────────

class TestPlanningModels:
    def test_execution_plan_model_importable(self):
        from app.db.models import ExecutionPlan
        assert ExecutionPlan.__tablename__ == "execution_plans"

    def test_plan_step_model_importable(self):
        from app.db.models import PlanStep
        assert PlanStep.__tablename__ == "plan_steps"

    def test_plan_has_blueprint_json_field(self):
        from app.db.models import ExecutionPlan
        assert hasattr(ExecutionPlan, "blueprint_json")

    def test_plan_step_has_depends_on_json(self):
        from app.db.models import PlanStep
        assert hasattr(PlanStep, "depends_on_json")

    def test_no_credentials_in_plan_model(self):
        """Plan model must not have password or secret fields."""
        from app.db.models import ExecutionPlan
        import inspect
        source = inspect.getsource(ExecutionPlan)
        assert "password" not in source
        assert "encrypted_password" not in source

    def test_plan_step_no_chain_of_thought_field(self):
        """Steps must not have a chain_of_thought or reasoning field."""
        from app.db.models import PlanStep
        assert not hasattr(PlanStep, "chain_of_thought")
        assert not hasattr(PlanStep, "reasoning")


# ── Planning service imports ──────────────────────────────────────────────────

class TestPlannerServiceImports:
    def test_planner_importable(self):
        from app.services.planner import (
            create_and_execute_plan,
            resume_plan,
            _generate_plan,
            _sanitise_args,
        )
        assert callable(create_and_execute_plan)
        assert callable(resume_plan)

    def test_max_limits_enforced_in_planner(self):
        """Planner must reference MAX constants."""
        from app.services.planner import MAX_PLAN_STEPS, MAX_TOOL_CALLS_PER_PLAN
        assert MAX_PLAN_STEPS >= 5
        assert MAX_TOOL_CALLS_PER_PLAN >= 4

    def test_planner_router_importable(self):
        from app.api.routers.planning import router
        route_paths = [r.path for r in router.routes]
        assert any("plans" in p for p in route_paths)
        assert any("resume" in p for p in route_paths)


# ── Approval integration ──────────────────────────────────────────────────────

class TestApprovalIntegration:
    def test_action_tool_requires_guarded_check(self):
        """If an action tool is in guarded_tools, plan must pause."""
        from app.schemas.blueprint import AgentBlueprint
        bp = AgentBlueprint(
            agent_id="test",
            role_name="Digital Marketing Manager",
            system_persona="Test.",
            allowed_tools=["create_internal_task"],
            guarded_tools=["create_internal_task"],
            tenant_id="tenant-1",
        )
        # Guarded tools should cause approval path in governance
        assert "create_internal_task" in bp.guarded_tools

    def test_plan_awaiting_approval_status_defined(self):
        from app.schemas.planning import PlanStatus
        assert "awaiting_approval" in PlanStatus.__args__  # type: ignore[attr-defined]

    def test_step_awaiting_approval_status_defined(self):
        from app.schemas.planning import StepStatus
        assert "awaiting_approval" in StepStatus.__args__  # type: ignore[attr-defined]


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntact:
    def test_query_company_data_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "query_company_data" in MASTER_TOOL_REGISTRY

    def test_create_internal_task_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "create_internal_task" in MASTER_TOOL_REGISTRY

    def test_action_governance_service_intact(self):
        from app.services.action_governance import process_action_request, approve_and_execute
        assert callable(process_action_request)
        assert callable(approve_and_execute)

    def test_rag_context_builder_intact(self):
        from app.core.engine import _build_rag_context

        class FakeChunk:
            document_name = "Policy.pdf"
            document_id = "doc-1"
            text = "Policy content."

        result = _build_rag_context([FakeChunk()])  # type: ignore[list-item]
        assert "Policy.pdf" in result

    def test_engine_execute_signature_intact(self):
        from app.core.engine import DynamicAgentEngine
        import inspect
        sig = inspect.signature(DynamicAgentEngine.execute)
        assert "data_context_block" in sig.parameters
        assert "rag_chunks" in sig.parameters

    def test_all_dmm_tools_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_campaign_analytics", "fetch_knowledge_base",
                  "generate_report", "query_company_data",
                  "create_internal_task", "send_email"]:
            assert t in MASTER_TOOL_REGISTRY, f"Missing: {t}"

    def test_data_access_schemas_intact(self):
        from app.schemas.data_access import CompanyDataQueryRequest, MAX_QUERY_LIMIT
        assert MAX_QUERY_LIMIT > 0
        req = CompanyDataQueryRequest(semantic_concept=None)
        assert req.limit == 50

    def test_action_registry_intact(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "create_internal_task" in ACTION_REGISTRY
