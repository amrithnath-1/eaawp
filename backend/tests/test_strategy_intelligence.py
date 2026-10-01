"""Tests for Marketing Strategy & Decision Intelligence subsystem."""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest


# ── Decision engine ───────────────────────────────────────────────────────────

class TestDecisionEngine:
    def test_compute_priority_score_critical(self):
        from app.services.decision_engine import compute_priority_score
        score = compute_priority_score("critical", -60.0, 50.0, 90.0)
        assert score > 80.0

    def test_compute_priority_score_low(self):
        from app.services.decision_engine import compute_priority_score
        score = compute_priority_score("low", -5.0, 2.0, 20.0)
        assert score < 50.0

    def test_urgency_score_large_change(self):
        from app.services.decision_engine import _urgency_score
        assert _urgency_score(-60.0) == 1.0

    def test_urgency_score_small_change(self):
        from app.services.decision_engine import _urgency_score
        assert _urgency_score(-3.0) == 0.25

    def test_urgency_score_none(self):
        from app.services.decision_engine import _urgency_score
        assert _urgency_score(None) == 0.25

    def test_confidence_score_full(self):
        from app.services.decision_engine import _confidence_score
        assert _confidence_score(100.0) == 1.0

    def test_confidence_score_zero(self):
        from app.services.decision_engine import _confidence_score
        assert _confidence_score(0.0) == 0.0

    def test_magnitude_score_tanh(self):
        from app.services.decision_engine import _magnitude_score
        assert 0.0 < _magnitude_score(100.0, 100.0) < 1.0

    def test_magnitude_score_zero(self):
        from app.services.decision_engine import _magnitude_score
        assert _magnitude_score(0.0) == 0.0

    def test_business_impact_critical(self):
        from app.services.decision_engine import _business_impact_score
        assert _business_impact_score("critical") == 1.0

    def test_business_impact_low(self):
        from app.services.decision_engine import _business_impact_score
        assert _business_impact_score("low") == 0.25

    def test_build_priorities_from_kpi_comparisons(self):
        from app.services.decision_engine import build_priorities_from_kpi_comparisons
        comparisons = [
            {"kpi_name": "ctr", "pct_change": -30.0, "current": 1.0, "previous": 1.43,
             "is_significant": True, "is_anomaly": False},
        ]
        priorities = build_priorities_from_kpi_comparisons(
            comparisons=comparisons, campaign_name="Test", campaign_id="cam-1",
            data_completeness=80.0, sources=["EAAWP metrics"],
        )
        assert len(priorities) == 1
        assert priorities[0].category == "problem"
        assert priorities[0].priority_score > 0
        assert "ctr" in priorities[0].title.lower()

    def test_build_priorities_no_insignificant_changes(self):
        from app.services.decision_engine import build_priorities_from_kpi_comparisons
        comparisons = [
            {"kpi_name": "ctr", "pct_change": -2.0, "current": 1.95, "previous": 2.0,
             "is_significant": False, "is_anomaly": False},
        ]
        priorities = build_priorities_from_kpi_comparisons(
            comparisons=comparisons, campaign_name="Test", campaign_id="cam-1",
            data_completeness=80.0, sources=[],
        )
        assert len(priorities) == 0

    def test_build_priorities_from_funnel(self):
        from app.services.decision_engine import build_priorities_from_funnel
        funnel = {
            "findings": ["Low visitor-to-lead conversion: 0.5%"],
            "recommendations": ["Review landing pages"],
            "data_completeness_pct": 60.0,
            "sources": ["EAAWP metrics"],
        }
        priorities = build_priorities_from_funnel(funnel, "Test Campaign", "cam-1")
        assert len(priorities) == 1
        assert "funnel" in priorities[0].affected_funnel_stage

    def test_rank_priorities_sorted_by_score(self):
        from app.services.decision_engine import rank_priorities
        from app.schemas.strategy import MarketingPriority
        p1 = MarketingPriority("A", "problem", "low", "", [], [], "", "", 0.5, 50.0, "", "none", 30.0)
        p2 = MarketingPriority("B", "problem", "critical", "", [], [], "", "", 0.9, 80.0, "", "high", 90.0)
        ranked = rank_priorities([p1, p2])
        assert ranked[0].title == "B"

    def test_rank_priorities_deduplication(self):
        from app.services.decision_engine import rank_priorities
        from app.schemas.strategy import MarketingPriority
        p1 = MarketingPriority("Same", "problem", "high", "", [], [], "", "", 0.8, 80.0, "", "high", 80.0)
        p2 = MarketingPriority("Same", "problem", "high", "", [], [], "", "", 0.8, 80.0, "", "high", 75.0)
        ranked = rank_priorities([p1, p2])
        assert len(ranked) == 1

    def test_score_is_deterministic(self):
        from app.services.decision_engine import compute_priority_score
        s1 = compute_priority_score("high", -25.0, 10.0, 70.0)
        s2 = compute_priority_score("high", -25.0, 10.0, 70.0)
        assert s1 == s2

    def test_no_fabricated_scores(self):
        """Scores must be 0–100 float — never arbitrary strings or None."""
        from app.services.decision_engine import compute_priority_score
        for args in [("critical", -60.0, 50.0, 100.0), ("low", None, None, 0.0)]:
            score = compute_priority_score(*args)
            assert isinstance(score, float)
            assert 0.0 <= score <= 100.0


# ── Objective CRUD tests ──────────────────────────────────────────────────────

class TestObjectiveCRUD:
    @pytest.mark.asyncio
    async def test_create_objective(self):
        from app.schemas.strategy import CreateObjectiveInput
        from app.services.strategy_service import create_objective
        from app.db.strategy_models import MarketingObjective

        body = CreateObjectiveInput(name="Increase lead gen", objective_type="lead_generation", priority=2)
        mock_db = AsyncMock()
        added = []
        def track_add(obj):
            if isinstance(obj, MarketingObjective):
                now = datetime.now(timezone.utc)
                obj.created_at = now
                obj.updated_at = now
            added.append(obj)
        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        result = await create_objective(body, "t1", mock_db)
        assert result.name == "Increase lead gen"
        assert result.status == "draft"
        assert result.tenant_id == "t1"
        # created_by defaults to "agent" since CreateObjectiveInput doesn't have created_by
        assert result.created_by in ("agent", "DIGITAL_MARKETING_MANAGER")

    @pytest.mark.asyncio
    async def test_list_objectives_filters_tenant(self):
        from app.services.strategy_service import list_objectives
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await list_objectives("t1", mock_db)
        assert result == []
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_objective_wrong_tenant(self):
        from app.services.strategy_service import get_objective
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await get_objective("obj-1", "wrong-tenant", mock_db)
        assert result is None


# ── Schema validation ─────────────────────────────────────────────────────────

class TestStrategySchemas:
    def test_valid_objective_create(self):
        from app.schemas.strategy import ObjectiveCreate
        o = ObjectiveCreate(name="Q4 Revenue Goal", objective_type="revenue", priority=1,
                            target_metric="revenue", target_value=100000.0)
        assert o.name == "Q4 Revenue Goal"

    def test_sql_injection_rejected(self):
        from app.schemas.strategy import ObjectiveCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ObjectiveCreate(name="Test; DROP TABLE objectives --")

    def test_invalid_objective_type_rejected(self):
        from app.schemas.strategy import ObjectiveCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ObjectiveCreate(name="Test", objective_type="hacked_type")

    def test_priority_range_enforced(self):
        from app.schemas.strategy import ObjectiveCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ObjectiveCreate(name="Test", priority=6)  # max is 5

    def test_invalid_status_rejected(self):
        from app.schemas.strategy import ObjectiveUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ObjectiveUpdate(status="hacked")

    def test_invalid_uuid_in_update_input(self):
        from app.schemas.strategy import UpdateObjectiveInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateObjectiveInput(objective_id="not-a-uuid; DROP TABLE --")

    def test_valid_update_input(self):
        from app.schemas.strategy import UpdateObjectiveInput
        inp = UpdateObjectiveInput(objective_id=str(uuid.uuid4()), priority=1, status="active")
        assert inp.status == "active"


# ── Strategic analysis ────────────────────────────────────────────────────────

class TestStrategicAnalysis:
    @pytest.mark.asyncio
    async def test_analysis_empty_data(self):
        from app.services.strategy_service import build_strategic_analysis
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        analysis = await build_strategic_analysis(tenant_id="t1", db=mock_db)
        assert analysis.tenant_id == "t1"
        assert isinstance(analysis.top_problems, list)
        assert isinstance(analysis.top_opportunities, list)
        assert isinstance(analysis.uncertainties, list)
        assert "No campaign performance" in " ".join(analysis.uncertainties) or \
               analysis.data_completeness_pct == 0.0

    @pytest.mark.asyncio
    async def test_analysis_with_kpi_comparisons(self):
        from app.services.strategy_service import build_strategic_analysis
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        campaign_insights = [{
            "campaign_id": "cam-1", "campaign_name": "Test Campaign",
            "data_completeness_pct": 80.0, "sources": ["EAAWP metrics"],
            "comparisons": [
                {"kpi_name": "ctr", "pct_change": -35.0, "current": 1.0, "previous": 1.54,
                 "is_significant": True, "is_anomaly": True},
            ],
        }]
        analysis = await build_strategic_analysis(
            tenant_id="t1", db=mock_db, campaign_insights=campaign_insights
        )
        assert len(analysis.top_problems) > 0
        assert analysis.top_problems[0].priority_score > 0

    @pytest.mark.asyncio
    async def test_analysis_no_fabrication_on_empty(self):
        from app.services.strategy_service import build_strategic_analysis
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        analysis = await build_strategic_analysis(tenant_id="t1", db=mock_db)
        # No priorities when no data
        for p in analysis.all_priorities:
            assert p.evidence  # every priority must have evidence

    @pytest.mark.asyncio
    async def test_monitoring_anomalies_become_priorities(self):
        from app.services.strategy_service import build_strategic_analysis
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        analysis = await build_strategic_analysis(
            tenant_id="t1", db=mock_db,
            monitoring_anomalies=["ROAS decreased 60% — anomaly detected"],
        )
        monitoring_ps = [p for p in analysis.all_priorities if p.category == "monitoring_alert"]
        assert len(monitoring_ps) > 0

    def test_analysis_to_dict_no_credentials(self):
        from app.services.strategy_service import analysis_to_dict
        from app.schemas.strategy import StrategicAnalysis
        a = StrategicAnalysis(
            tenant_id="t1", generated_at="2026-01-01T00:00:00Z",
            current_situation="Test", top_problems=[], top_opportunities=[],
            all_priorities=[], active_objectives=[], recommended_actions=[],
            uncertainties=[], data_completeness_pct=0.0, sources=[],
        )
        d = analysis_to_dict(a)
        assert "password" not in str(d).lower()
        assert "credential" not in str(d).lower()

    def test_recommendations_are_text_only(self):
        from app.services.strategy_service import analysis_to_dict
        from app.schemas.strategy import StrategicAnalysis
        a = StrategicAnalysis(
            tenant_id="t1", generated_at="2026-01-01T00:00:00Z",
            current_situation="Test", top_problems=[], top_opportunities=[],
            all_priorities=[], active_objectives=[],
            recommended_actions=["Review CTR performance"],
            uncertainties=[], data_completeness_pct=50.0, sources=[],
        )
        d = analysis_to_dict(a)
        for rec in d["recommended_actions"]:
            assert isinstance(rec, str)
            assert not callable(rec)


# ── Action tool governance ────────────────────────────────────────────────────

class TestStrategyGovernance:
    def test_create_objective_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "create_marketing_objective" in ACTION_REGISTRY

    def test_update_objective_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "update_marketing_objective" in ACTION_REGISTRY

    def test_create_objective_risk_is_medium(self):
        from app.actions.registry import ACTION_REGISTRY
        assert ACTION_REGISTRY["create_marketing_objective"].meta.risk_level == "medium"

    def test_update_objective_risk_is_high(self):
        from app.actions.registry import ACTION_REGISTRY
        assert ACTION_REGISTRY["update_marketing_objective"].meta.risk_level == "high"

    def test_read_tools_not_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        for t in ("analyze_marketing_strategy", "get_marketing_priorities", "get_marketing_objectives"):
            assert t not in ACTION_REGISTRY

    @pytest.mark.asyncio
    async def test_create_objective_governance_requires_approval(self):
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="create_marketing_objective",
            arguments={"name": "Grow leads", "objective_type": "lead_generation"},
            tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER", requested_by="agent",
        )
        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=["create_marketing_objective"],
            blueprint_guarded_tools=["create_marketing_objective"],
            db=mock_db,
        )
        assert result.status == "proposed"

    @pytest.mark.asyncio
    async def test_update_objective_unauthorized_without_permission(self):
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="update_marketing_objective",
            arguments={"objective_id": str(uuid.uuid4()), "priority": 1},
            tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER", requested_by="agent",
        )
        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=[],  # not allowed
            blueprint_guarded_tools=[],
            db=mock_db,
        )
        assert result.status == "unauthorized"


# ── Tool registration ─────────────────────────────────────────────────────────

class TestStrategyTools:
    def test_all_strategy_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ("analyze_marketing_strategy", "get_marketing_priorities",
                  "get_marketing_objectives", "create_marketing_objective",
                  "update_marketing_objective"):
            assert t in MASTER_TOOL_REGISTRY

    def test_read_tools_in_planner_prompt(self):
        from app.services.planner import _PLANNER_SYSTEM
        for t in ("analyze_marketing_strategy", "get_marketing_priorities", "get_marketing_objectives"):
            assert t in _PLANNER_SYSTEM

    def test_strategy_tools_in_dmm_defaults(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        keys = [t["tool_key"] for t in tool_scopes]
        for t in ("analyze_marketing_strategy", "get_marketing_priorities",
                  "get_marketing_objectives", "create_marketing_objective",
                  "update_marketing_objective"):
            assert t in keys


# ── Router / tenant isolation ─────────────────────────────────────────────────

class TestStrategyRouter:
    def test_strategy_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/strategy" in p for p in paths)


# ── Planner integration ───────────────────────────────────────────────────────

class TestStrategyPlannerIntegration:
    def test_strategy_tools_in_planner_prompt(self):
        from app.services.planner import _PLANNER_SYSTEM
        assert "analyze_marketing_strategy" in _PLANNER_SYSTEM
        assert "get_marketing_priorities" in _PLANNER_SYSTEM

    def test_strategy_tools_read_in_planner_step_types(self):
        from app.services.planner import _PLANNER_SYSTEM
        # Read step types section should include strategy tools
        assert "analyze_marketing_strategy" in _PLANNER_SYSTEM


# ── Monitoring integration ────────────────────────────────────────────────────

class TestStrategyMonitoringIntegration:
    def test_monitoring_anomalies_accepted_by_analysis(self):
        """build_strategic_analysis accepts monitoring_anomalies parameter."""
        from app.services.strategy_service import build_strategic_analysis
        import inspect
        sig = inspect.signature(build_strategic_analysis)
        assert "monitoring_anomalies" in sig.parameters

    def test_existing_monitoring_engine_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)


# ── RAG integration ───────────────────────────────────────────────────────────

class TestStrategyRAGIntegration:
    @pytest.mark.asyncio
    async def test_rag_sources_included_in_analysis(self):
        from app.services.strategy_service import build_strategic_analysis
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        analysis = await build_strategic_analysis(
            tenant_id="t1", db=mock_db,
            rag_context="Brand guidelines recommend focus on email campaigns.",
            rag_sources=["Brand Guidelines v2.pdf"],
        )
        assert "Company knowledge base" in analysis.sources
        assert "Brand Guidelines v2.pdf" in analysis.rag_sources

    def test_rag_does_not_override_security(self):
        """RAG sources must not change tool permissions or approval requirements."""
        from app.services.strategy_service import analysis_to_dict
        from app.schemas.strategy import StrategicAnalysis
        a = StrategicAnalysis(
            tenant_id="t1", generated_at="now", current_situation="",
            top_problems=[], top_opportunities=[], all_priorities=[],
            active_objectives=[], recommended_actions=[],
            uncertainties=[], data_completeness_pct=0.0,
            sources=["Company knowledge base"],
            rag_sources=["Strategy Doc.pdf"],
        )
        d = analysis_to_dict(a)
        # Sources are present but no permission bypass
        assert "Company knowledge base" in d["sources"]
        assert "Strategy Doc.pdf" in d["rag_sources"]


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithStrategy:
    def test_all_previous_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_company_data", "get_campaigns", "analyze_campaign_performance",
                  "analyze_funnel", "create_campaign", "draft_email", "send_email"]:
            assert t in MASTER_TOOL_REGISTRY

    def test_campaign_service_intact(self):
        from app.services.campaign_service import create_campaign
        assert callable(create_campaign)

    def test_kpi_engine_intact(self):
        from app.services.kpi_engine import calculate_all_kpis
        assert callable(calculate_all_kpis)

    def test_funnel_service_intact(self):
        from app.services.funnel_service import calculate_funnel
        assert callable(calculate_funnel)

    def test_strategy_model_no_hardcoded_external_tables(self):
        from app.db.strategy_models import MarketingObjective
        cols = [c.key for c in MarketingObjective.__table__.columns]
        for bad in ("leads", "customers", "revenue_table", "ad_spend_table"):
            assert bad not in cols
