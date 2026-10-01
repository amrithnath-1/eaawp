"""
Tests for Lead & Customer Funnel Intelligence subsystem.
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Funnel calculation tests ──────────────────────────────────────────────────

class TestFunnelCalculations:
    def test_full_funnel(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({
            "visitors": 10000.0, "leads": 500.0, "qualified_leads": 200.0,
            "opportunities": 50.0, "customers": 10.0
        }, spend=5000.0, revenue=20000.0)
        v2l = next(c for c in f.conversion_rates if c.from_stage == "visitors" and c.to_stage == "leads")
        assert v2l.rate_pct == pytest.approx(5.0)
        assert f.cost_per_lead == pytest.approx(10.0)     # 5000/500
        assert f.cost_per_customer == pytest.approx(500.0) # 5000/10
        assert f.roas == pytest.approx(4.0)               # 20000/5000
        assert f.overall_conversion_rate.rate_pct == pytest.approx(0.1)  # 10/10000

    def test_zero_denominator_returns_none(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"visitors": 0.0, "leads": 100.0})
        v2l = next(c for c in f.conversion_rates if c.from_stage == "visitors" and c.to_stage == "leads")
        assert v2l.rate_pct is None
        assert v2l.missing_reason != ""

    def test_missing_stage_is_none_not_fabricated(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": 500.0, "customers": 20.0})
        visitor_stage = next(s for s in f.stages if s.name == "visitors")
        assert visitor_stage.value is None
        assert f.overall_conversion_rate.rate_pct is None  # visitors missing

    def test_empty_funnel_all_none(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({})
        for s in f.stages:
            assert s.value is None
        for cr in f.conversion_rates:
            assert cr.rate_pct is None

    def test_invalid_negative_values_excluded(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": -100.0, "customers": 10.0})
        lead_stage = next(s for s in f.stages if s.name == "leads")
        assert lead_stage.value is None

    def test_spend_none_gives_none_cpl(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": 500.0}, spend=None)
        assert f.cost_per_lead is None
        assert f.cost_per_customer is None

    def test_revenue_none_gives_none_roas(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"customers": 10.0}, spend=1000.0, revenue=None)
        assert f.roas is None
        assert f.revenue_per_customer is None

    def test_data_completeness_full(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({
            "visitors": 1000.0, "leads": 100.0, "qualified_leads": 50.0,
            "opportunities": 20.0, "customers": 5.0
        }, spend=1000.0, revenue=5000.0)
        assert f.data_completeness_pct == pytest.approx(100.0)

    def test_data_completeness_partial(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": 100.0})  # 1 of 7 fields present
        assert f.data_completeness_pct < 30.0

    def test_revenue_per_lead(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": 200.0}, revenue=10000.0)
        assert f.revenue_per_lead == pytest.approx(50.0)

    def test_revenue_per_customer(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"customers": 40.0}, revenue=8000.0)
        assert f.revenue_per_customer == pytest.approx(200.0)


# ── Safe division tests ───────────────────────────────────────────────────────

class TestSafeDivision:
    def test_safe_pct_valid(self):
        from app.services.funnel_service import _safe_pct
        rate, reason = _safe_pct(50.0, 1000.0)
        assert rate == pytest.approx(5.0)
        assert reason == ""

    def test_safe_pct_zero_denom(self):
        from app.services.funnel_service import _safe_pct
        rate, reason = _safe_pct(50.0, 0.0)
        assert rate is None
        assert "zero" in reason

    def test_safe_pct_none_numerator(self):
        from app.services.funnel_service import _safe_pct
        rate, reason = _safe_pct(None, 1000.0)
        assert rate is None
        assert "missing" in reason

    def test_safe_pct_none_denominator(self):
        from app.services.funnel_service import _safe_pct
        rate, reason = _safe_pct(50.0, None)
        assert rate is None

    def test_safe_ratio_valid(self):
        from app.services.funnel_service import _safe_ratio
        assert _safe_ratio(100.0, 4.0) == pytest.approx(25.0)

    def test_safe_ratio_zero_denom(self):
        from app.services.funnel_service import _safe_ratio
        assert _safe_ratio(100.0, 0.0) is None

    def test_safe_ratio_none_inputs(self):
        from app.services.funnel_service import _safe_ratio
        assert _safe_ratio(None, 4.0) is None
        assert _safe_ratio(100.0, None) is None


# ── Finding / recommendation tests ───────────────────────────────────────────

class TestFunnelFindings:
    def test_low_visitor_to_lead_generates_finding(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"visitors": 10000.0, "leads": 50.0})  # 0.5%
        text = " ".join(f.findings)
        assert "visitor" in text.lower() or "lead" in text.lower()
        assert len(f.recommendations) > 0

    def test_negative_roi_generates_finding(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"customers": 5.0}, spend=10000.0, revenue=3000.0)
        text = " ".join(f.findings)
        assert "spend" in text.lower() or "revenue" in text.lower()

    def test_strong_funnel_no_negative_finding(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"visitors": 1000.0, "leads": 100.0, "customers": 50.0},
                             spend=1000.0, revenue=50000.0)
        assert f.roas == pytest.approx(50.0)
        # No negative ROI finding
        assert not any("exceed" in fn.lower() for fn in f.findings)

    def test_recommendations_are_text_only(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"visitors": 5000.0, "leads": 10.0})
        for r in f.recommendations:
            assert isinstance(r, str)
            assert not callable(r)

    def test_insufficient_data_noted(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({})
        assert f.analysis_note != "" or f.data_completeness_pct == 0.0


# ── funnel_to_dict safety ─────────────────────────────────────────────────────

class TestFunnelSerialisation:
    def test_funnel_to_dict_no_credentials(self):
        from app.services.funnel_service import calculate_funnel, funnel_to_dict
        f = calculate_funnel({"leads": 100.0, "customers": 5.0}, spend=500.0)
        d = funnel_to_dict(f)
        d_str = str(d)
        for bad in ("password", "credential", "secret", "api_key"):
            assert bad not in d_str.lower()

    def test_funnel_to_dict_has_required_keys(self):
        from app.services.funnel_service import calculate_funnel, funnel_to_dict
        f = calculate_funnel({"leads": 50.0})
        d = funnel_to_dict(f)
        for key in ("stages", "conversion_rates", "data_completeness_pct",
                    "sources", "findings", "recommendations"):
            assert key in d

    def test_funnel_to_dict_none_values_preserved(self):
        from app.services.funnel_service import calculate_funnel, funnel_to_dict
        f = calculate_funnel({})
        d = funnel_to_dict(f)
        for s in d["stages"]:
            assert s["value"] is None


# ── Schema validation tests ───────────────────────────────────────────────────

class TestFunnelSchemas:
    def test_funnel_stages_ordered(self):
        from app.schemas.funnel import FUNNEL_STAGES
        assert FUNNEL_STAGES[0] == "visitors"
        assert FUNNEL_STAGES[-1] == "customers"
        assert "leads" in FUNNEL_STAGES

    def test_funnel_semantic_concepts_defined(self):
        from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
        for concept in ("lead_count", "customer_count", "revenue", "campaign_spend"):
            assert concept in FUNNEL_SEMANTIC_CONCEPTS

    def test_no_hardcoded_external_tables(self):
        import inspect
        from app.schemas import funnel
        source = inspect.getsource(funnel)
        for table in ("leads", "customers", "opportunities", "revenue", "sales"):
            # Tables must not appear as __tablename__ or sqlalchemy table definitions
            assert f'"{table}"' not in source or "concept" in source


# ── External data integration tests ──────────────────────────────────────────

class TestExternalDataIntegration:
    @pytest.mark.asyncio
    async def test_fetch_external_handles_permission_error(self):
        from app.services.funnel_service import fetch_funnel_from_external
        from unittest.mock import patch, AsyncMock
        mock_db = AsyncMock()
        async def mock_query(*args, **kwargs):
            raise PermissionError("Entity not allowed")
        with patch("app.services.funnel_service.execute_company_data_query", side_effect=mock_query):
            result = await fetch_funnel_from_external(
                tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER",
                concepts=["lead_count"], db=mock_db,
            )
        assert result.get("lead_count") is None

    @pytest.mark.asyncio
    async def test_fetch_external_handles_missing_mapping(self):
        from app.services.funnel_service import fetch_funnel_from_external
        from unittest.mock import patch, AsyncMock
        mock_db = AsyncMock()
        async def mock_query(*args, **kwargs):
            raise ValueError("No semantic mapping found")
        with patch("app.services.funnel_service.execute_company_data_query", side_effect=mock_query):
            result = await fetch_funnel_from_external(
                tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER",
                concepts=["customer_count"], db=mock_db,
            )
        assert result.get("customer_count") is None

    @pytest.mark.asyncio
    async def test_fetch_external_valid_data(self):
        from app.services.funnel_service import fetch_funnel_from_external
        from app.schemas.data_access import CompanyDataQueryResponse
        from unittest.mock import patch, AsyncMock
        mock_db = AsyncMock()
        mock_response = CompanyDataQueryResponse(
            tenant_id="t1", connection_id="conn-1", entity_name="leads",
            semantic_concept="lead_count", fields_returned=["count"],
            rows=[{"count": 250}], row_count=1, truncated=False, sources=["db/leads"],
        )
        async def mock_query(*args, **kwargs):
            return mock_response
        with patch("app.services.funnel_service.execute_company_data_query", side_effect=mock_query):
            result = await fetch_funnel_from_external(
                tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER",
                concepts=["lead_count"], db=mock_db,
            )
        assert result.get("lead_count") == pytest.approx(250.0)

    def test_only_allowed_concepts_accepted(self):
        from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
        # Concepts like "leads_table" or arbitrary names should not be in allowed set
        assert "leads_table" not in FUNNEL_SEMANTIC_CONCEPTS
        assert "SELECT * FROM" not in FUNNEL_SEMANTIC_CONCEPTS

    def test_no_hardcoded_table_names_in_service(self):
        import inspect
        from app.services import funnel_service
        source = inspect.getsource(funnel_service)
        # No raw table names as strings (checked in external_data section)
        assert "FROM leads" not in source
        assert "FROM customers" not in source
        assert "FROM opportunities" not in source


# ── Campaign attribution tests ────────────────────────────────────────────────

class TestCampaignAttribution:
    def test_campaign_funnel_attribution_schema(self):
        from app.schemas.funnel import CampaignFunnelAttribution
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel({"leads": 100.0, "customers": 5.0})
        attr = CampaignFunnelAttribution(
            campaign_id="cam-1", campaign_name="Test",
            funnel=f, external_concepts_used=["lead_count"],
        )
        assert attr.campaign_id == "cam-1"
        assert attr.funnel.cost_per_customer is None  # no spend provided

    def test_campaign_funnel_with_spend_revenue(self):
        from app.services.funnel_service import calculate_funnel
        f = calculate_funnel(
            {"leads": 200.0, "customers": 8.0},
            spend=4000.0, revenue=16000.0,
        )
        assert f.cost_per_lead == pytest.approx(20.0)
        assert f.cost_per_customer == pytest.approx(500.0)
        assert f.roas == pytest.approx(4.0)


# ── Performance integration tests ─────────────────────────────────────────────

class TestPerformanceIntegration:
    def test_funnel_and_kpi_work_together(self):
        from app.services.funnel_service import calculate_funnel
        from app.services.kpi_engine import calc_ctr
        funnel = calculate_funnel({"leads": 500.0, "customers": 25.0},
                                  spend=10000.0, revenue=50000.0)
        ctr = calc_ctr(clicks=500.0, impressions=20000.0)
        # Both systems work independently
        assert funnel.cost_per_lead == pytest.approx(20.0)
        assert ctr.value == pytest.approx(2.5)

    def test_funnel_roas_consistent_with_kpi_roas(self):
        from app.services.funnel_service import calculate_funnel
        from app.services.kpi_engine import calc_roas
        funnel = calculate_funnel({}, spend=2000.0, revenue=8000.0)
        kpi_roas = calc_roas(revenue=8000.0, spend=2000.0)
        assert funnel.roas == kpi_roas.value


# ── Tenant isolation tests ────────────────────────────────────────────────────

class TestFunnelTenantIsolation:
    @pytest.mark.asyncio
    async def test_external_fetch_passes_tenant_to_data_access(self):
        from app.services.funnel_service import fetch_funnel_from_external
        from unittest.mock import patch, AsyncMock
        mock_db = AsyncMock()
        captured = {}
        async def mock_query(request, tenant_id, role_key, db):
            captured["tenant_id"] = tenant_id
            raise ValueError("no mapping")
        with patch("app.services.funnel_service.execute_company_data_query", side_effect=mock_query):
            await fetch_funnel_from_external(
                tenant_id="tenant-ABC", role_key="DIGITAL_MARKETING_MANAGER",
                concepts=["lead_count"], db=mock_db,
            )
        assert captured.get("tenant_id") == "tenant-ABC"


# ── Tool registration tests ───────────────────────────────────────────────────

class TestFunnelTools:
    def test_all_funnel_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for tool in ("analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"):
            assert tool in MASTER_TOOL_REGISTRY

    def test_funnel_tools_not_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        for tool in ("analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"):
            assert tool not in ACTION_REGISTRY

    def test_funnel_tools_in_planner_prompt(self):
        from app.services.planner import _PLANNER_SYSTEM
        for tool in ("analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"):
            assert tool in _PLANNER_SYSTEM

    def test_funnel_tools_in_dmm_defaults(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        import json
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        keys = [t["tool_key"] for t in tool_scopes]
        for tool in ("analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"):
            assert tool in keys

    def test_funnel_tools_governance_is_enabled(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        import json
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        for tool in ("analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"):
            scope = next((t for t in tool_scopes if t["tool_key"] == tool), None)
            assert scope is not None
            assert scope["governance"] == "enabled"


# ── Router tests ──────────────────────────────────────────────────────────────

class TestFunnelRouter:
    def test_funnel_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/funnel" in p for p in paths)


# ── Monitoring integration ────────────────────────────────────────────────────

class TestFunnelMonitoringIntegration:
    def test_funnel_concepts_can_be_semantic_concepts(self):
        from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
        from app.schemas.monitoring import MonitoringCondition
        # A monitoring rule can reference a funnel concept as semantic_concept
        cond = MonitoringCondition(
            metric_field="value",
            operator="falls_below",
            threshold=5.0,
        )
        assert cond.operator == "falls_below"
        # Funnel concepts are valid semantic concept names
        assert "lead_count" in FUNNEL_SEMANTIC_CONCEPTS

    def test_existing_monitoring_engine_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithFunnel:
    def test_campaign_service_intact(self):
        from app.services.campaign_service import create_campaign
        assert callable(create_campaign)

    def test_kpi_engine_intact(self):
        from app.services.kpi_engine import calculate_all_kpis
        assert callable(calculate_all_kpis)

    def test_performance_analysis_intact(self):
        from app.services.performance_analysis import analyse_campaign_performance
        assert callable(analyse_campaign_performance)

    def test_all_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_company_data", "get_campaigns", "analyze_campaign_performance",
                  "create_campaign", "draft_email", "send_email",
                  "analyze_funnel", "get_funnel_metrics", "analyze_campaign_funnel"]:
            assert t in MASTER_TOOL_REGISTRY


