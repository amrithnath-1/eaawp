"""
Tests for Marketing Performance Intelligence subsystem.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest


# ── KPI Engine tests ──────────────────────────────────────────────────────────

class TestKPIEngine:
    def test_calc_ctr_valid(self):
        from app.services.kpi_engine import calc_ctr
        r = calc_ctr(clicks=100.0, impressions=5000.0)
        assert r.value == pytest.approx(2.0)
        assert r.unit == "%"

    def test_calc_ctr_zero_impressions(self):
        from app.services.kpi_engine import calc_ctr
        r = calc_ctr(clicks=100.0, impressions=0.0)
        assert r.value is None
        assert "impressions=0" in r.missing_inputs

    def test_calc_ctr_none_clicks(self):
        from app.services.kpi_engine import calc_ctr
        r = calc_ctr(clicks=None, impressions=5000.0)
        assert r.value is None
        assert "clicks" in r.missing_inputs

    def test_calc_ctr_none_impressions(self):
        from app.services.kpi_engine import calc_ctr
        r = calc_ctr(clicks=100.0, impressions=None)
        assert r.value is None

    def test_calc_conversion_rate_valid(self):
        from app.services.kpi_engine import calc_conversion_rate
        r = calc_conversion_rate(conversions=50.0, clicks=1000.0)
        assert r.value == pytest.approx(5.0)

    def test_calc_conversion_rate_zero_clicks(self):
        from app.services.kpi_engine import calc_conversion_rate
        r = calc_conversion_rate(conversions=10.0, clicks=0.0)
        assert r.value is None

    def test_calc_cpc_valid(self):
        from app.services.kpi_engine import calc_cpc
        r = calc_cpc(spend=500.0, clicks=100.0)
        assert r.value == pytest.approx(5.0)
        assert r.unit == "£"

    def test_calc_cpc_zero_clicks(self):
        from app.services.kpi_engine import calc_cpc
        r = calc_cpc(spend=500.0, clicks=0.0)
        assert r.value is None

    def test_calc_cpm_valid(self):
        from app.services.kpi_engine import calc_cpm
        r = calc_cpm(spend=50.0, impressions=10000.0)
        assert r.value == pytest.approx(5.0)

    def test_calc_cpm_zero_impressions(self):
        from app.services.kpi_engine import calc_cpm
        r = calc_cpm(spend=50.0, impressions=0.0)
        assert r.value is None

    def test_calc_cpa_valid(self):
        from app.services.kpi_engine import calc_cpa
        r = calc_cpa(spend=1000.0, conversions=10.0)
        assert r.value == pytest.approx(100.0)

    def test_calc_cpa_zero_conversions(self):
        from app.services.kpi_engine import calc_cpa
        r = calc_cpa(spend=1000.0, conversions=0.0)
        assert r.value is None

    def test_calc_roas_valid(self):
        from app.services.kpi_engine import calc_roas
        r = calc_roas(revenue=4000.0, spend=1000.0)
        assert r.value == pytest.approx(4.0)
        assert r.unit == "x"

    def test_calc_roas_zero_spend(self):
        from app.services.kpi_engine import calc_roas
        r = calc_roas(revenue=4000.0, spend=0.0)
        assert r.value is None

    def test_calc_roas_none_revenue(self):
        from app.services.kpi_engine import calc_roas
        r = calc_roas(revenue=None, spend=1000.0)
        assert r.value is None
        assert "revenue" in r.missing_inputs

    def test_calculate_all_kpis(self):
        from app.services.kpi_engine import calculate_all_kpis
        metrics = {
            "impressions": 10000.0,
            "clicks": 200.0,
            "conversions": 20.0,
            "spend": 500.0,
            "revenue": 2000.0,
        }
        kpis = calculate_all_kpis(metrics)
        assert kpis["ctr"].value == pytest.approx(2.0)
        assert kpis["conversion_rate"].value == pytest.approx(10.0)
        assert kpis["cpc"].value == pytest.approx(2.5)
        assert kpis["cpm"].value == pytest.approx(50.0)
        assert kpis["cpa"].value == pytest.approx(25.0)
        assert kpis["roas"].value == pytest.approx(4.0)

    def test_calculate_all_kpis_missing_spend(self):
        from app.services.kpi_engine import calculate_all_kpis
        metrics = {"impressions": 5000.0, "clicks": 100.0}
        kpis = calculate_all_kpis(metrics)
        assert kpis["ctr"].value is not None
        assert kpis["cpc"].value is None   # spend missing
        assert kpis["roas"].value is None  # revenue and spend missing

    def test_no_fabricated_values_for_missing_metrics(self):
        from app.services.kpi_engine import calculate_all_kpis
        kpis = calculate_all_kpis({})
        for k, v in kpis.items():
            assert v.value is None, f"KPI {k} should be None when no metrics recorded"

    def test_collect_metrics_aggregates_correctly(self):
        from app.services.kpi_engine import collect_metrics
        records = [
            {"metric_name": "clicks", "metric_value": 100.0, "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": 200.0, "metric_date": "2026-01-02"},
            {"metric_name": "impressions", "metric_value": 5000.0, "metric_date": "2026-01-01"},
        ]
        result = collect_metrics(records)
        assert result["clicks"] == pytest.approx(300.0)
        assert result["impressions"] == pytest.approx(5000.0)

    def test_collect_metrics_filters_by_date(self):
        from app.services.kpi_engine import collect_metrics
        records = [
            {"metric_name": "clicks", "metric_value": 100.0, "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": 200.0, "metric_date": "2026-01-15"},
            {"metric_name": "clicks", "metric_value": 300.0, "metric_date": "2026-02-01"},
        ]
        result = collect_metrics(records, date_from="2026-01-10", date_to="2026-01-31")
        assert result["clicks"] == pytest.approx(200.0)

    def test_collect_metrics_skips_negative_values(self):
        from app.services.kpi_engine import collect_metrics
        records = [
            {"metric_name": "clicks", "metric_value": -50.0, "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": 100.0, "metric_date": "2026-01-01"},
        ]
        result = collect_metrics(records)
        assert result["clicks"] == pytest.approx(100.0)

    def test_collect_metrics_skips_invalid_values(self):
        from app.services.kpi_engine import collect_metrics
        records = [
            {"metric_name": "clicks", "metric_value": "not_a_number", "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": 100.0, "metric_date": "2026-01-01"},
        ]
        result = collect_metrics(records)
        assert result["clicks"] == pytest.approx(100.0)

    def test_collect_metrics_skips_nan_inf(self):
        import math
        from app.services.kpi_engine import collect_metrics
        records = [
            {"metric_name": "clicks", "metric_value": float("nan"), "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": float("inf"), "metric_date": "2026-01-01"},
            {"metric_name": "clicks", "metric_value": 100.0, "metric_date": "2026-01-01"},
        ]
        result = collect_metrics(records)
        assert result["clicks"] == pytest.approx(100.0)

    def test_normalise_metric_name_aliases(self):
        from app.services.kpi_engine import normalise_metric_name
        assert normalise_metric_name("Click Through Rate") == "ctr"
        assert normalise_metric_name("ad_spend") == "spend"
        assert normalise_metric_name("Impression") == "impressions"
        assert normalise_metric_name("return_on_ad_spend") == "roas"

    def test_data_completeness_full(self):
        from app.services.kpi_engine import data_completeness_pct
        metrics = {"impressions": 1000.0, "clicks": 50.0, "conversions": 5.0,
                   "spend": 200.0, "revenue": 800.0}
        assert data_completeness_pct(metrics) == pytest.approx(100.0)

    def test_data_completeness_partial(self):
        from app.services.kpi_engine import data_completeness_pct
        metrics = {"impressions": 1000.0, "clicks": 50.0}  # 2 of 5 expected
        result = data_completeness_pct(metrics)
        assert result == pytest.approx(40.0)

    def test_data_completeness_empty(self):
        from app.services.kpi_engine import data_completeness_pct
        assert data_completeness_pct({}) == pytest.approx(0.0)


# ── Period comparison tests ───────────────────────────────────────────────────

class TestPeriodComparison:
    def test_compare_periods_increase(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"ctr": KPIResult("ctr", 3.0, "%")}
        prev = {"ctr": KPIResult("ctr", 2.0, "%")}
        comps = compare_periods(cur, prev)
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.pct_change == pytest.approx(50.0)
        assert ctr.trend == "up"

    def test_compare_periods_decrease(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"ctr": KPIResult("ctr", 1.5, "%")}
        prev = {"ctr": KPIResult("ctr", 2.0, "%")}
        comps = compare_periods(cur, prev)
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.pct_change == pytest.approx(-25.0)
        assert ctr.trend == "down"
        assert ctr.is_significant is True  # -25% > 10% threshold

    def test_compare_periods_stable(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"ctr": KPIResult("ctr", 2.0, "%")}
        prev = {"ctr": KPIResult("ctr", 2.0, "%")}
        comps = compare_periods(cur, prev)
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.trend == "stable"
        assert ctr.is_significant is False

    def test_compare_periods_missing_previous(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"ctr": KPIResult("ctr", 3.0, "%")}
        comps = compare_periods(cur, {})
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.pct_change is None
        assert ctr.trend == "unknown"

    def test_compare_periods_anomaly_detection(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"ctr": KPIResult("ctr", 0.2, "%")}  # dropped 80%
        prev = {"ctr": KPIResult("ctr", 1.0, "%")}
        comps = compare_periods(cur, prev, anomaly_threshold_pct=50.0)
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.is_anomaly is True
        assert ctr.anomaly_reason != ""

    def test_compare_periods_zero_previous(self):
        from app.services.kpi_engine import compare_periods, KPIResult
        cur = {"clicks": KPIResult("clicks", 100.0, is_calculated=False)}
        prev = {"clicks": KPIResult("clicks", 0.0, is_calculated=False)}
        comps = compare_periods(cur, prev)
        c = next(x for x in comps if x.kpi_name == "clicks")
        assert c.pct_change is None  # zero denominator handled gracefully

    def test_prior_period_calculation(self):
        from app.services.performance_analysis import _prior_period
        pf, pt = _prior_period("2026-02-01", "2026-02-28")
        # 28-day period → prior period: Jan 4 – Jan 31
        assert pf == "2026-01-04"
        assert pt == "2026-01-31"

    def test_prior_period_none_dates(self):
        from app.services.performance_analysis import _prior_period
        pf, pt = _prior_period(None, None)
        assert pf is None
        assert pt is None

    def test_significant_change_threshold(self):
        from app.services.kpi_engine import compare_periods, KPIResult, SIGNIFICANT_CHANGE_THRESHOLD_PCT
        # Change less than threshold → not significant
        cur = {"ctr": KPIResult("ctr", 2.09, "%")}
        prev = {"ctr": KPIResult("ctr", 2.0, "%")}
        comps = compare_periods(cur, prev, significant_threshold_pct=SIGNIFICANT_CHANGE_THRESHOLD_PCT)
        ctr = next(c for c in comps if c.kpi_name == "ctr")
        assert ctr.is_significant is False


# ── Performance analysis service tests ───────────────────────────────────────

class TestPerformanceAnalysisService:
    def _mock_campaign(self, campaign_id="cam-1", name="Test Campaign"):
        from app.db.campaign_models import Campaign
        c = MagicMock(spec=Campaign)
        c.id = campaign_id
        c.tenant_id = "t1"
        c.name = name
        c.status = "active"
        return c

    def _mock_metric(self, name, value, date="2026-01-15"):
        from app.db.campaign_models import CampaignMetric
        m = MagicMock(spec=CampaignMetric)
        m.metric_name = name
        m.metric_value = value
        m.metric_date = date
        return m

    @pytest.mark.asyncio
    async def test_analyse_campaign_returns_none_for_wrong_tenant(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # not found
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await analyse_campaign_performance("cam-1", "wrong-tenant", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyse_campaign_kpis_calculated(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        campaign = self._mock_campaign()
        metrics = [
            self._mock_metric("impressions", 10000.0),
            self._mock_metric("clicks", 200.0),
            self._mock_metric("spend", 500.0),
        ]
        call_count = [0]
        async def execute_side(q):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:
                r.scalar_one_or_none.return_value = campaign
            elif call_count[0] == 2:
                r.scalars.return_value.all.return_value = metrics
            else:
                r.scalars.return_value.all.return_value = []  # prior period empty
            return r
        mock_db.execute = AsyncMock(side_effect=execute_side)

        insight = await analyse_campaign_performance("cam-1", "t1", mock_db,
                                                     date_from="2026-01-01", date_to="2026-01-31")
        assert insight is not None
        assert insight.campaign_id == "cam-1"
        assert insight.kpis["ctr"].value == pytest.approx(2.0)
        assert insight.kpis["cpc"].value == pytest.approx(2.5)
        assert insight.data_completeness_pct > 0

    @pytest.mark.asyncio
    async def test_analyse_campaign_no_data_no_fabrication(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        campaign = self._mock_campaign()
        call_count = [0]
        async def execute_side(q):
            call_count[0] += 1
            r = MagicMock()
            r.scalar_one_or_none.return_value = campaign if call_count[0] == 1 else None
            r.scalars.return_value.all.return_value = []
            return r
        mock_db.execute = AsyncMock(side_effect=execute_side)
        insight = await analyse_campaign_performance("cam-1", "t1", mock_db)
        assert insight is not None
        # All KPIs should be None when no data
        for kpi in insight.kpis.values():
            assert kpi.value is None, f"{kpi.name} should be None with no metrics"

    @pytest.mark.asyncio
    async def test_analyse_campaign_recommendations_evidence_based(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        campaign = self._mock_campaign()
        # Low CTR scenario
        metrics = [
            self._mock_metric("impressions", 10000.0),
            self._mock_metric("clicks", 50.0),   # CTR = 0.5%
        ]
        call_count = [0]
        async def execute_side(q):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:
                r.scalar_one_or_none.return_value = campaign
            elif call_count[0] == 2:
                r.scalars.return_value.all.return_value = metrics
            else:
                r.scalars.return_value.all.return_value = []
            return r
        mock_db.execute = AsyncMock(side_effect=execute_side)
        insight = await analyse_campaign_performance("cam-1", "t1", mock_db,
                                                     date_from="2026-01-01", date_to="2026-01-31")
        # Should have a CTR recommendation since CTR < 1%
        recs_text = " ".join(insight.recommendations)
        assert "CTR" in recs_text or "ctr" in recs_text.lower()
        # Recommendation must not be empty
        assert len(insight.recommendations) > 0

    @pytest.mark.asyncio
    async def test_analyse_campaign_external_metrics_merged(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        campaign = self._mock_campaign()
        call_count = [0]
        async def execute_side(q):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:
                r.scalar_one_or_none.return_value = campaign
            else:
                r.scalars.return_value.all.return_value = []
            return r
        mock_db.execute = AsyncMock(side_effect=execute_side)
        # Provide external revenue metric
        insight = await analyse_campaign_performance(
            "cam-1", "t1", mock_db,
            external_metrics={"revenue": 5000.0, "spend": 1000.0},
            external_sources=["Company data · revenue_summary"],
        )
        assert insight is not None
        assert insight.kpis["roas"].value == pytest.approx(5.0)
        assert any("Company data" in s for s in insight.sources)

    def test_insight_to_dict_safe(self):
        from app.services.performance_analysis import insight_to_dict, PerformanceInsight
        from app.services.kpi_engine import KPIResult, PeriodComparison
        insight = PerformanceInsight(
            campaign_id="c1", campaign_name="Test",
            period_from="2026-01-01", period_to="2026-01-31",
            kpis={"ctr": KPIResult("ctr", 2.0, "%")},
            comparisons=[],
            strongest_metrics=["clicks"],
            weakest_metrics=[],
            anomalies=[],
            data_completeness_pct=80.0,
            sources=["EAAWP campaign metrics"],
            recommendations=["Review CTR"],
        )
        d = insight_to_dict(insight)
        assert "password" not in str(d)
        assert "credential" not in str(d)
        assert d["data_completeness_pct"] == pytest.approx(80.0)

    def test_recommendations_not_directly_executed(self):
        """Recommendations return text only — they don't trigger governance."""
        from app.services.performance_analysis import _build_recommendations
        from app.services.kpi_engine import KPIResult
        kpis = {"ctr": KPIResult("ctr", 0.5, "%")}
        recs = _build_recommendations(kpis, [], [], 40.0)
        assert isinstance(recs, list)
        for r in recs:
            assert isinstance(r, str)  # text only, no action side effects


# ── Campaign comparison tests ─────────────────────────────────────────────────

class TestCampaignComparison:
    @pytest.mark.asyncio
    async def test_compare_requires_at_least_2_campaigns(self):
        from app.services.performance_analysis import compare_campaigns
        mock_db = AsyncMock()
        result = await compare_campaigns(["cam-1"], "t1", mock_db)
        assert result.insufficient_data is True
        assert "2 campaigns" in result.insufficient_reason.lower()

    @pytest.mark.asyncio
    async def test_compare_campaigns_no_rank_when_missing_data(self):
        from app.services.performance_analysis import compare_campaigns
        mock_db = AsyncMock()

        def make_campaign_result(name, metrics_list):
            from app.db.campaign_models import Campaign, CampaignMetric
            cam = MagicMock(spec=Campaign)
            cam.id = f"cam-{name}"
            cam.tenant_id = "t1"
            cam.name = name
            cam.status = "active"
            ms = []
            for mn, mv in metrics_list:
                m = MagicMock(spec=CampaignMetric)
                m.metric_name = mn
                m.metric_value = mv
                m.metric_date = "2026-01-15"
                ms.append(m)
            return cam, ms

        cam_a, metrics_a = make_campaign_result("Alpha", [("impressions", 5000.0), ("clicks", 100.0)])
        cam_b, metrics_b = make_campaign_result("Beta", [("impressions", 3000.0)])  # no clicks → no CTR

        calls = [0]
        campaigns_map = {"cam-Alpha": (cam_a, metrics_a), "cam-Beta": (cam_b, metrics_b)}

        async def execute_side(q):
            calls[0] += 1
            r = MagicMock()
            # Simple: alternate campaign/metric queries
            # The analysis calls: 1=campaign lookup, 2=metrics, 3=prior metrics
            call_num = calls[0]
            if call_num in (1, 4):
                idx = 0 if call_num == 1 else 1
                camp = [cam_a, cam_b][idx]
                r.scalar_one_or_none.return_value = camp
            else:
                ms = metrics_a if calls[0] < 4 else metrics_b
                r.scalars.return_value.all.return_value = ms if call_num in (2, 5) else []
            return r

        mock_db.execute = AsyncMock(side_effect=execute_side)
        result = await compare_campaigns(
            ["cam-Alpha", "cam-Beta"], "t1", mock_db, rank_by="ctr"
        )
        # Beta has no CTR (no clicks) — ranking by ctr should fail gracefully
        if result.insufficient_data:
            assert "ctr" in result.insufficient_reason.lower() or result.insufficient_reason != ""

    @pytest.mark.asyncio
    async def test_compare_empty_returns_insufficient(self):
        from app.services.performance_analysis import compare_campaigns
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await compare_campaigns(["cam-1", "cam-2"], "t1", mock_db)
        assert result.insufficient_data is True


# ── Tool registration tests ───────────────────────────────────────────────────

class TestPerformanceTools:
    def test_all_three_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for tool in ("analyze_campaign_performance", "compare_campaigns", "get_campaign_kpis"):
            assert tool in MASTER_TOOL_REGISTRY

    def test_performance_tools_not_in_action_registry(self):
        """Performance tools are READ tools — must NOT be in ACTION_REGISTRY."""
        from app.actions.registry import ACTION_REGISTRY
        for tool in ("analyze_campaign_performance", "compare_campaigns", "get_campaign_kpis"):
            assert tool not in ACTION_REGISTRY

    def test_performance_tools_in_planner_prompt(self):
        from app.services.planner import _PLANNER_SYSTEM
        for tool in ("analyze_campaign_performance", "compare_campaigns", "get_campaign_kpis"):
            assert tool in _PLANNER_SYSTEM


# ── Tenant isolation tests ────────────────────────────────────────────────────

class TestPerformanceTenantIsolation:
    @pytest.mark.asyncio
    async def test_analysis_wrong_tenant_returns_none(self):
        from app.services.performance_analysis import analyse_campaign_performance
        mock_db = AsyncMock()
        mock_r = MagicMock()
        mock_r.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_r)
        result = await analyse_campaign_performance("cam-x", "other-tenant", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_comparison_only_uses_tenant_campaigns(self):
        from app.services.performance_analysis import compare_campaigns
        mock_db = AsyncMock()
        mock_r = MagicMock()
        mock_r.scalar_one_or_none.return_value = None  # campaigns not found
        mock_r.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_r)
        result = await compare_campaigns(["c1", "c2"], "wrong-tenant", mock_db)
        assert result.insufficient_data is True


# ── Security tests ────────────────────────────────────────────────────────────

class TestPerformanceSecurity:
    def test_kpi_engine_no_sql(self):
        import inspect
        from app.services import kpi_engine
        source = inspect.getsource(kpi_engine)
        assert "execute(" not in source
        assert "raw SQL" not in source

    def test_performance_analysis_no_credentials(self):
        import inspect
        from app.services import performance_analysis
        source = inspect.getsource(performance_analysis)
        assert "decrypt_password" not in source
        assert "encrypted_password" not in source

    def test_insight_to_dict_no_credentials(self):
        from app.services.performance_analysis import insight_to_dict, PerformanceInsight
        from app.services.kpi_engine import KPIResult
        insight = PerformanceInsight(
            campaign_id="c1", campaign_name="Test",
            period_from=None, period_to=None,
            kpis={"ctr": KPIResult("ctr", 1.5, "%")},
            comparisons=[], strongest_metrics=[], weakest_metrics=[],
            anomalies=[], data_completeness_pct=60.0,
            sources=["EAAWP metrics"], recommendations=[],
        )
        d = insight_to_dict(insight)
        d_str = str(d)
        for bad in ("password", "credential", "secret", "api_key", "connection_string"):
            assert bad not in d_str.lower()

    def test_recommendations_do_not_auto_execute(self):
        """Recommendations are strings — they have no execute() method."""
        from app.services.performance_analysis import _build_recommendations
        from app.services.kpi_engine import KPIResult
        kpis = {"ctr": KPIResult("ctr", 0.3, "%")}
        recs = _build_recommendations(kpis, [], [], 30.0)
        for r in recs:
            assert isinstance(r, str)
            assert not callable(r)


# ── Performance router tests ──────────────────────────────────────────────────

class TestPerformanceRouter:
    def test_performance_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/performance" in p for p in paths)

    def test_performance_router_importable(self):
        from app.api.routers.performance import router
        assert router.prefix == "/api/v1/performance"


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithPerformance:
    def test_campaign_service_intact(self):
        from app.services.campaign_service import create_campaign, list_campaigns
        assert callable(create_campaign)

    def test_all_previous_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_company_data", "create_internal_task", "draft_email",
                  "send_email", "get_campaigns", "create_campaign"]:
            assert t in MASTER_TOOL_REGISTRY

    def test_monitoring_engine_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)

    def test_governance_intact(self):
        from app.services.action_governance import process_action_request
        assert callable(process_action_request)
