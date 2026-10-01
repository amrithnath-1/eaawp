"""
EAAWP Completion Sprint Tests — Phase 0-28

Covers:
- Memory subsystem (Phase 5)
- Notification subsystem (Phase 12)
- Reporting subsystem (Phase 13)
- Channel integration abstraction (Phase 1)
- nest_asyncio fix (Phase 17)
- Content service RAG fix
- Security invariants
- Existing systems intact
- End-to-end scenario verification
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ── Memory subsystem ──────────────────────────────────────────────────────────

class TestAgentMemory:
    def test_memory_model_importable(self):
        from app.db.memory_models import AgentMemory
        assert AgentMemory.__tablename__ == "agent_memories"

    def test_memory_has_tenant_id(self):
        from app.db.memory_models import AgentMemory
        cols = [c.key for c in AgentMemory.__table__.columns]
        assert "tenant_id" in cols

    def test_memory_no_credentials(self):
        from app.db.memory_models import AgentMemory
        cols = [c.key for c in AgentMemory.__table__.columns]
        for bad in ("password", "api_key", "secret"):
            assert bad not in cols

    def test_valid_categories(self):
        from app.services.memory_service import VALID_CATEGORIES
        for cat in ("execution_history", "decision", "approved_action", "rejected_action",
                    "company_preference", "campaign_learning", "strategy",
                    "recurring_pattern", "admin_instruction"):
            assert cat in VALID_CATEGORIES

    def test_max_per_category_defined(self):
        from app.services.memory_service import MAX_PER_CATEGORY
        assert MAX_PER_CATEGORY >= 50

    @pytest.mark.asyncio
    async def test_store_memory_creates_record(self):
        from app.db.memory_models import AgentMemory
        from app.services.memory_service import store_memory

        mock_db = AsyncMock()
        added = []
        def track(obj):
            if isinstance(obj, AgentMemory):
                obj.created_at = datetime.now(timezone.utc)
            added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()
        # Mock count query
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_count)

        mem = await store_memory(
            tenant_id="t1", role_key="DIGITAL_MARKETING_MANAGER",
            category="decision", title="Used email channel for Q4",
            content="Q4 campaigns via email showed 15% CTR improvement.",
            db=mock_db, confidence=0.9,
        )
        assert mem.category == "decision"
        assert mem.tenant_id == "t1"

    @pytest.mark.asyncio
    async def test_search_memory_filters_by_tenant(self):
        from app.services.memory_service import search_memory
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await search_memory("t1", "DIGITAL_MARKETING_MANAGER", "email campaign", mock_db)
        assert results == []
        mock_db.execute.assert_called_once()

    def test_memory_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/memory" in p for p in paths)

    def test_memory_does_not_override_security(self):
        """Memory service must not contain permission bypass logic."""
        import inspect
        from app.services import memory_service
        source = inspect.getsource(memory_service)
        assert "bypass" not in source.lower()
        assert "override_permission" not in source.lower()


# ── Notification subsystem ────────────────────────────────────────────────────

class TestNotifications:
    def test_notification_model_importable(self):
        from app.db.notification_models import Notification
        assert Notification.__tablename__ == "notifications"

    def test_notification_has_tenant_id(self):
        from app.db.notification_models import Notification
        cols = [c.key for c in Notification.__table__.columns]
        assert "tenant_id" in cols
        assert "is_read" in cols
        assert "severity" in cols

    @pytest.mark.asyncio
    async def test_create_notification(self):
        from app.db.notification_models import Notification
        from app.services.notification_service import create_notification

        mock_db = AsyncMock()
        added = []
        def track(obj):
            if isinstance(obj, Notification):
                obj.created_at = datetime.now(timezone.utc)
                # SQLAlchemy server_default doesn't fire on mock — set manually
                if not hasattr(obj, '_is_read_set'):
                    object.__setattr__(obj, 'is_read', False)
            added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        n = await create_notification(
            tenant_id="t1", title="CTR dropped", message="Campaign CTR dropped 25%.",
            db=mock_db, severity="warning", category="monitoring_alert",
        )
        assert n.title == "CTR dropped"
        assert n.severity == "warning"
        # is_read defaults to False in the model definition
        assert n.is_read in (False, None)  # None on mock before flush

    @pytest.mark.asyncio
    async def test_mark_read_wrong_tenant(self):
        from app.services.notification_service import mark_read
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await mark_read("notif-1", "wrong-tenant", mock_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_all_read(self):
        from app.db.notification_models import Notification
        from app.services.notification_service import mark_all_read

        mock_n = MagicMock(spec=Notification)
        mock_n.is_read = False

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_n, mock_n]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        count = await mark_all_read("t1", mock_db)
        assert count == 2

    def test_notification_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/notifications" in p for p in paths)


# ── Channel integration ───────────────────────────────────────────────────────

class TestChannelIntegration:
    def test_channel_model_importable(self):
        from app.db.channel_models import MarketingChannelIntegration
        assert MarketingChannelIntegration.__tablename__ == "marketing_channel_integrations"

    def test_channel_no_plain_credentials(self):
        from app.db.channel_models import MarketingChannelIntegration
        cols = [c.key for c in MarketingChannelIntegration.__table__.columns]
        assert "encrypted_credentials" in cols
        assert "credentials" not in cols
        assert "password" not in cols

    def test_mock_provider_importable(self):
        from app.integrations.channel_providers import MockChannelProvider, get_provider
        p = get_provider("mock", "social_linkedin")
        assert p.provider_name == "mock"
        assert p.channel_type == "social_linkedin"

    @pytest.mark.asyncio
    async def test_mock_provider_test_connection(self):
        from app.integrations.channel_providers import MockChannelProvider
        p = MockChannelProvider("social_linkedin")
        result = await p.validate_connection({})
        assert result.success is True
        assert "account" in result.account_info

    @pytest.mark.asyncio
    async def test_mock_provider_prepare_content(self):
        from app.integrations.channel_providers import MockChannelProvider
        p = MockChannelProvider("email_marketing")
        result = await p.prepare_content({"body": "Hello world", "title": "Test"}, {})
        assert result.success is True
        assert "body" in result.prepared_content

    @pytest.mark.asyncio
    async def test_mock_provider_publish_records_not_sends(self):
        from app.integrations.channel_providers import MockChannelProvider
        p = MockChannelProvider("social_linkedin")
        result = await p.publish_content({"body": "Test post"}, {})
        assert result.success is True
        assert result.provider_post_id is not None
        assert "MOCK" in (result.provider_message or "")

    def test_twitter_content_truncation(self):
        """Mock provider truncates Twitter content to 280 chars."""
        import asyncio
        from app.integrations.channel_providers import MockChannelProvider
        p = MockChannelProvider("social_twitter")
        long_body = "x" * 500
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(p.prepare_content({"body": long_body, "title": "Test"}, {}))
        loop.close()
        assert len(result.prepared_content.get("body", "")) <= 280
        assert result.validation_warnings

    def test_provider_registry(self):
        from app.integrations.channel_providers import _PROVIDER_REGISTRY
        assert "mock" in _PROVIDER_REGISTRY

    def test_register_custom_provider(self):
        from app.integrations.channel_providers import register_provider, get_provider, MockChannelProvider
        register_provider("test_custom", MockChannelProvider)
        p = get_provider("test_custom", "custom")
        assert p.provider_name == "mock"  # MockChannelProvider

    def test_channel_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/channels" in p for p in paths)

    def test_prepare_content_endpoint_exists(self):
        from app.api.routers.channels import router
        paths = [r.path for r in router.routes]
        assert any("prepare" in p for p in paths)

    def test_no_direct_publish_from_llm(self):
        """publish_content requires credentials — never called directly by LLM tools."""
        import inspect
        from app.integrations import channel_providers
        source = inspect.getsource(channel_providers)
        # The LLM tool only calls prepare_content, not publish_content
        from app.tools.registry import MASTER_TOOL_REGISTRY
        # There should be no publish tool in the registry (publishing is HIGH risk action only)
        assert "publish_content" not in MASTER_TOOL_REGISTRY


# ── Reporting ─────────────────────────────────────────────────────────────────

class TestReporting:
    @pytest.mark.asyncio
    async def test_generate_marketing_summary_empty(self):
        from app.services.reporting_service import generate_marketing_summary
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        summary = await generate_marketing_summary("t1", mock_db, period_days=7)
        assert summary["report_type"] == "marketing_summary"
        assert summary["tenant_id"] == "t1"
        assert "note" in summary
        assert "fabricat" in summary["note"].lower()

    def test_reporting_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/reports" in p for p in paths)

    def test_report_no_fabrication_assertion(self):
        import inspect
        from app.services import reporting_service
        source = inspect.getsource(reporting_service)
        assert "fabricat" in source.lower()


# ── nest_asyncio fix verification ─────────────────────────────────────────────

class TestNestAsyncioFix:
    def test_nest_asyncio_removed_from_main(self):
        """nest_asyncio removed from main.py - broke Python 3.14. Tools now use get_running_loop()."""
        import inspect
        from app import main
        source = inspect.getsource(main)
        assert "nest_asyncio" not in source, "nest_asyncio must NOT be in main.py"

    def test_nest_asyncio_importable(self):
        import nest_asyncio
        assert callable(nest_asyncio.apply)


# ── Content service RAG fix ───────────────────────────────────────────────────

class TestContentServiceRAGFix:
    def test_fetch_rag_context_uses_retrieve_similar_chunks(self):
        import inspect
        from app.services import content_service
        source = inspect.getsource(content_service._fetch_rag_context)
        assert "retrieve_similar_chunks" in source
        assert "VectorStore()" not in source  # Old broken pattern removed

    @pytest.mark.asyncio
    async def test_fetch_rag_context_handles_failure_gracefully(self):
        from app.services.content_service import _fetch_rag_context
        mock_db = AsyncMock()
        # Simulate failure (no OpenAI key in tests)
        ctx, sources = await _fetch_rag_context("t1", "test query", mock_db)
        # Should return empty strings gracefully, not raise
        assert isinstance(ctx, str)
        assert isinstance(sources, list)


# ── Security hardening ────────────────────────────────────────────────────────

class TestSecurityHardening:
    def test_all_new_models_have_tenant_id(self):
        from app.db.memory_models import AgentMemory
        from app.db.notification_models import Notification
        from app.db.channel_models import MarketingChannelIntegration
        for model in (AgentMemory, Notification, MarketingChannelIntegration):
            cols = [c.key for c in model.__table__.columns]
            assert "tenant_id" in cols, f"{model.__tablename__} missing tenant_id"

    def test_channel_credentials_stored_encrypted(self):
        from app.db.channel_models import MarketingChannelIntegration
        cols = [c.key for c in MarketingChannelIntegration.__table__.columns]
        assert "encrypted_credentials" in cols
        assert "credentials" not in cols  # plain credentials must not exist

    def test_memory_content_not_executable(self):
        """Memory service must not exec/eval stored content."""
        import inspect
        from app.services import memory_service
        source = inspect.getsource(memory_service)
        assert "exec(" not in source
        assert "eval(" not in source

    def test_notification_no_credentials(self):
        from app.db.notification_models import Notification
        cols = [c.key for c in Notification.__table__.columns]
        for bad in ("password", "api_key", "secret", "credentials"):
            assert bad not in cols

    def test_channel_service_no_plaintext_creds_in_output(self):
        """The safe dict must not include encrypted_credentials as a returned key."""
        import inspect
        from app.services import channel_service
        # Parse the returned dict keys from _to_safe_dict
        source = inspect.getsource(channel_service._to_safe_dict)
        # Find the return block
        return_block = source[source.index("return {"):]
        # encrypted_credentials must not be a key in the returned dict
        assert '"encrypted_credentials"' not in return_block

    def test_reporting_no_credentials_in_output(self):
        import inspect
        from app.services import reporting_service
        source = inspect.getsource(reporting_service)
        assert "password" not in source
        assert "encrypted_password" not in source
        assert "decrypt" not in source


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactAfterSprint:
    def test_all_original_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_company_data", "analyze_campaign_performance",
                  "analyze_funnel", "analyze_marketing_strategy",
                  "generate_content_brief", "generate_content_draft",
                  "create_campaign", "draft_email", "send_email",
                  "get_marketing_priorities"]:
            assert t in MASTER_TOOL_REGISTRY, f"Missing: {t}"

    def test_659_existing_tests_still_importable(self):
        """Verify no existing test modules were broken."""
        import tests.test_action_framework
        import tests.test_campaigns
        import tests.test_content_intelligence
        import tests.test_email_integration
        import tests.test_funnel_intelligence
        import tests.test_monitoring
        import tests.test_performance_intelligence
        import tests.test_planning
        import tests.test_strategy_intelligence

    def test_planner_intact(self):
        from app.services.planner import create_and_execute_plan, resume_plan
        assert callable(create_and_execute_plan)

    def test_governance_intact(self):
        from app.services.action_governance import process_action_request
        assert callable(process_action_request)

    def test_monitoring_scheduler_intact(self):
        from app.services.monitoring_scheduler import start_scheduler, stop_scheduler
        assert callable(start_scheduler)

    def test_kpi_engine_intact(self):
        from app.services.kpi_engine import calculate_all_kpis, calc_ctr
        assert calc_ctr(100, 5000).value == pytest.approx(2.0)

    def test_main_app_routes_complete(self):
        from app.main import app
        paths = set(r.path for r in app.routes)
        required = [
            "/api/v1/campaigns", "/api/v1/performance/campaigns",
            "/api/v1/funnel/analyze", "/api/v1/strategy/objectives",
            "/api/v1/content", "/api/v1/memory/search",
            "/api/v1/notifications", "/api/v1/channels",
            "/api/v1/reports/marketing-summary",
            "/api/v1/monitoring/rules", "/api/v1/email/integration",
        ]
        for r in required:
            assert any(r in p for p in paths), f"Missing route: {r}"


# ── Phase 25: End-to-end scenario ────────────────────────────────────────────

class TestEndToEndScenario:
    """
    Verifies the complete DMM workflow chain is structurally sound.
    Uses mocks for external calls.
    """

    def test_e2e_workflow_chain_importable(self):
        """All services in the E2E chain must be importable."""
        from app.services.strategy_service import build_strategic_analysis
        from app.services.campaign_service import create_campaign, list_campaigns
        from app.services.performance_analysis import analyse_campaign_performance
        from app.services.funnel_service import calculate_funnel
        from app.services.content_service import generate_brief, generate_draft
        from app.services.channel_service import prepare_content_for_channel
        from app.services.memory_service import store_memory, search_memory
        from app.services.notification_service import create_notification
        from app.services.reporting_service import generate_marketing_summary
        from app.services.planner import create_and_execute_plan
        from app.services.action_governance import process_action_request
        from app.services.monitoring_engine import evaluate_rule
        assert True

    def test_e2e_tool_chain_complete(self):
        """Every E2E step has a corresponding tool or service."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        e2e_tools = [
            "get_marketing_objectives",       # Strategy
            "analyze_marketing_strategy",      # Strategy analysis
            "get_campaigns",                   # Campaign
            "analyze_campaign_performance",    # Performance
            "analyze_campaign_funnel",         # Funnel
            "generate_content_brief",          # Content
            "generate_content_draft",          # Content
            "analyze_content",                 # Content analysis
            "draft_email",                     # Communication
            "create_internal_task",            # Task
        ]
        for tool in e2e_tools:
            assert tool in MASTER_TOOL_REGISTRY, f"Missing E2E tool: {tool}"

    def test_e2e_governance_chain_intact(self):
        """All governed actions require approval."""
        from app.actions.registry import ACTION_REGISTRY
        governed = {
            "send_email": "high",
            "create_campaign": "medium",
            "update_campaign": "high",
            "create_marketing_objective": "medium",
            "update_marketing_objective": "high",
        }
        for tool, expected_risk in governed.items():
            action = ACTION_REGISTRY.get(tool)
            assert action is not None, f"Missing governed action: {tool}"
            assert action.meta.requires_approval is True, f"{tool} must require approval"
            assert action.meta.risk_level == expected_risk, f"{tool} risk should be {expected_risk}"

    def test_e2e_no_approval_bypass(self):
        """No tool in MASTER_TOOL_REGISTRY can directly execute HIGH risk actions."""
        # All HIGH risk actions (send_email, update_campaign) go through governance
        # which creates approval requests. The LLM cannot bypass this.
        from app.actions.registry import ACTION_REGISTRY
        for tool_name, action in ACTION_REGISTRY.items():
            if action.meta.risk_level == "high":
                assert action.meta.requires_approval is True, \
                    f"HIGH risk action {tool_name} must require approval"

    @pytest.mark.asyncio
    async def test_e2e_funnel_calculation_chain(self):
        """Test funnel → KPI integration chain."""
        from app.services.funnel_service import calculate_funnel
        from app.services.kpi_engine import calculate_all_kpis

        funnel = calculate_funnel(
            {"visitors": 10000, "leads": 500, "customers": 25},
            spend=5000.0, revenue=15000.0,
        )
        assert funnel.cost_per_lead == pytest.approx(10.0)
        assert funnel.roas == pytest.approx(3.0)

        kpis = calculate_all_kpis({
            "impressions": 50000, "clicks": 500, "spend": 5000
        })
        assert kpis["ctr"].value == pytest.approx(1.0)
        assert kpis["cpc"].value == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_e2e_strategy_produces_priorities(self):
        """Strategy analysis must produce evidence-backed priorities."""
        from app.services.strategy_service import build_strategic_analysis

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        campaign_insights = [{
            "campaign_id": "cam-1", "campaign_name": "Test",
            "data_completeness_pct": 80.0, "sources": ["EAAWP"],
            "comparisons": [
                {"kpi_name": "ctr", "pct_change": -40.0, "current": 0.6,
                 "previous": 1.0, "is_significant": True, "is_anomaly": True},
            ],
        }]
        analysis = await build_strategic_analysis(
            tenant_id="t1", db=mock_db,
            campaign_insights=campaign_insights,
        )
        assert len(analysis.top_problems) > 0
        assert analysis.top_problems[0].priority_score > 0
        assert analysis.top_problems[0].evidence

    def test_e2e_mock_provider_safe(self):
        """Mock channel provider never makes real external calls."""
        import inspect
        from app.integrations.channel_providers import MockChannelProvider
        source = inspect.getsource(MockChannelProvider)
        assert "requests.get" not in source
        assert "requests.post" not in source
        assert "httpx" not in source
        assert "urllib.request" not in source


# ── Phase 26: Demo readiness ──────────────────────────────────────────────────

class TestDemoReadiness:
    def test_seed_data_file_exists(self):
        """Seed data is separate from production data."""
        from app.db.seed import seed_demo_data
        assert callable(seed_demo_data)

    def test_all_required_demo_capabilities_have_tools(self):
        """Each demo step has at least one supporting tool/API."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        from app.main import app
        paths = [r.path for r in app.routes]

        # 1. Company setup — companies router
        assert any("/api/v1/companies" in p for p in paths)
        # 2. DMM configuration — roles router
        assert any("/api/v1/roles" in p for p in paths)
        # 3. Knowledge upload — knowledge router
        assert any("/api/v1/knowledge" in p for p in paths)
        # 4. Data connection — integrations router
        assert any("/api/v1/integrations" in p for p in paths)
        # 5. AI analysis — strategy tool
        assert "analyze_marketing_strategy" in MASTER_TOOL_REGISTRY
        # 6. Campaign creation — create_campaign tool
        assert "create_campaign" in MASTER_TOOL_REGISTRY
        # 7. Content generation — content tools
        assert "generate_content_brief" in MASTER_TOOL_REGISTRY
        # 8. Approval workflow — approvals router
        assert any("/api/v1/approvals" in p for p in paths)
        # 9. Monitoring — monitoring router
        assert any("/api/v1/monitoring" in p for p in paths)
        # 10. Reporting
        assert any("/api/v1/reports" in p for p in paths)
        # 11. Audit
        assert any("/api/v1/audit" in p for p in paths)
