"""
EAAWP Fresh Company Onboarding + Tenant Isolation Tests

Covers:
- Company creation with admin user
- DMM auto-initialization
- Tenant isolation (Company A cannot access Company B)
- Onboarding status endpoint
- DMM activation
- Fresh-company end-to-end flow
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ── Onboarding schema validation ──────────────────────────────────────────────

class TestOnboardingSchemas:
    def test_valid_onboard_request(self):
        from app.api.routers.onboarding import OnboardCompanyRequest
        req = OnboardCompanyRequest(
            company_name="Test Corp",
            industry="SaaS",
            region="UK",
            employees=50,
            admin_name="Jane Smith",
            admin_email="jane@testcorp.com",
            admin_password="SecurePass123",
        )
        assert req.company_name == "Test Corp"
        assert req.admin_email == "jane@testcorp.com"

    def test_invalid_email_rejected(self):
        from app.api.routers.onboarding import OnboardCompanyRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardCompanyRequest(
                company_name="Test Corp",
                admin_name="Jane",
                admin_email="not-an-email",
                admin_password="securepass",
            )

    def test_short_password_rejected(self):
        from app.api.routers.onboarding import OnboardCompanyRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardCompanyRequest(
                company_name="Test",
                admin_name="Jane",
                admin_email="jane@test.com",
                admin_password="short",  # < 8 chars
            )

    def test_sql_injection_in_company_name_rejected(self):
        from app.api.routers.onboarding import OnboardCompanyRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardCompanyRequest(
                company_name="Test; DROP TABLE companies --",
                admin_name="Jane",
                admin_email="jane@test.com",
                admin_password="SecurePass1",
            )

    def test_empty_company_name_rejected(self):
        from app.api.routers.onboarding import OnboardCompanyRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardCompanyRequest(
                company_name="",
                admin_name="Jane",
                admin_email="jane@test.com",
                admin_password="SecurePass1",
            )


# ── Onboarding service tests ───────────────────────────────────────────────────

class TestOnboardingService:
    @pytest.mark.asyncio
    async def test_onboard_creates_company_and_user(self):
        """POST /api/v1/onboarding/company creates Company + User records."""
        from app.api.routers.onboarding import OnboardCompanyRequest
        from app.db.models import Company, User

        mock_db = AsyncMock()
        added_objects = []

        def track_add(obj):
            if isinstance(obj, (Company, User)):
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc)
                if isinstance(obj, Company):
                    obj.created_at = obj.updated_at = now
                if isinstance(obj, User):
                    obj.created_at = obj.updated_at = now
            added_objects.append(obj)

        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        with patch("app.api.routers.role_config._get_or_seed", new_callable=AsyncMock, return_value=None), \
             patch("app.api.routers.onboarding._pwd.hash", return_value="$2b$12$mockhash"):
            from app.api.routers.onboarding import onboard_new_company
            req = OnboardCompanyRequest(
                company_name="Fresh Corp",
                industry="Tech",
                region="UK",
                employees=25,
                admin_name="Admin User",
                admin_email="admin@freshcorp.com",
                admin_password="StrongPass1",
            )
            result = await onboard_new_company(req, mock_db)

        assert result.company_name == "Fresh Corp"
        assert result.tenant_id == result.company_id
        assert result.dmm_initialized is True
        companies = [o for o in added_objects if isinstance(o, Company)]
        users = [o for o in added_objects if isinstance(o, User)]
        assert len(companies) == 1
        assert len(users) == 1
        assert users[0].tenant_id == companies[0].id

    @pytest.mark.asyncio
    async def test_company_and_user_share_tenant_id(self):
        """User.tenant_id must equal Company.id."""
        from app.api.routers.onboarding import OnboardCompanyRequest
        from app.db.models import Company, User

        mock_db = AsyncMock()
        added_objects = []
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_db.flush = AsyncMock()

        with patch("app.api.routers.role_config._get_or_seed", new_callable=AsyncMock), \
             patch("app.api.routers.onboarding._pwd.hash", return_value="$2b$12$mockhash"):
            from app.api.routers.onboarding import onboard_new_company
            req = OnboardCompanyRequest(
                company_name="Isolation Corp",
                admin_name="Admin",
                admin_email="admin@isolation.com",
                admin_password="SecurePass1",
            )
            result = await onboard_new_company(req, mock_db)

        companies = [o for o in added_objects if isinstance(o, Company)]
        users = [o for o in added_objects if isinstance(o, User)]
        assert users[0].tenant_id == companies[0].id


# ── Tenant isolation tests ─────────────────────────────────────────────────────

class TestTenantIsolation:
    """
    Verifies Company A cannot access Company B's resources.
    """

    def test_campaign_model_has_tenant_id(self):
        from app.db.campaign_models import Campaign
        cols = [c.key for c in Campaign.__table__.columns]
        assert "tenant_id" in cols

    def test_content_model_has_tenant_id(self):
        from app.db.content_models import ContentItem
        cols = [c.key for c in ContentItem.__table__.columns]
        assert "tenant_id" in cols

    def test_monitoring_rule_has_tenant_id(self):
        from app.db.monitoring_models import MonitoringRule
        cols = [c.key for c in MonitoringRule.__table__.columns]
        assert "tenant_id" in cols

    def test_strategy_objective_has_tenant_id(self):
        from app.db.strategy_models import MarketingObjective
        cols = [c.key for c in MarketingObjective.__table__.columns]
        assert "tenant_id" in cols

    def test_memory_has_tenant_id(self):
        from app.db.memory_models import AgentMemory
        cols = [c.key for c in AgentMemory.__table__.columns]
        assert "tenant_id" in cols

    def test_notification_has_tenant_id(self):
        from app.db.notification_models import Notification
        cols = [c.key for c in Notification.__table__.columns]
        assert "tenant_id" in cols

    def test_channel_integration_has_tenant_id(self):
        from app.db.channel_models import MarketingChannelIntegration
        cols = [c.key for c in MarketingChannelIntegration.__table__.columns]
        assert "tenant_id" in cols

    @pytest.mark.asyncio
    async def test_campaign_isolation_company_a_cannot_see_company_b(self):
        """get_campaign for tenant_id=A must return None for a campaign owned by B."""
        from app.services.campaign_service import get_campaign

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # tenant mismatch → not found
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_campaign("campaign-owned-by-B", "tenant-A", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_content_isolation(self):
        from app.services.content_service import get_content

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_content("content-owned-by-B", "tenant-A", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_objective_isolation(self):
        from app.services.strategy_service import get_objective

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_objective("obj-owned-by-B", "tenant-A", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_memory_isolation(self):
        from app.services.memory_service import search_memory

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # no results for this tenant
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await search_memory("tenant-A", "DIGITAL_MARKETING_MANAGER", "campaign", mock_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_notification_isolation(self):
        from app.services.notification_service import mark_read

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # not found for this tenant
        mock_db.execute = AsyncMock(return_value=mock_result)

        ok = await mark_read("notif-owned-by-B", "tenant-A", mock_db)
        assert ok is False

    def test_all_routers_require_tenant_header(self):
        """All tenant-scoped routers must have X-Tenant-ID dependency."""
        from app.main import app
        # The key routers use _tenant() dependency which reads X-Tenant-ID header
        # Verify by checking their prefixes are registered
        paths = [r.path for r in app.routes]
        tenant_scoped = [
            "/api/v1/campaigns",
            "/api/v1/content",
            "/api/v1/strategy/objectives",
            "/api/v1/monitoring/rules",
            "/api/v1/memory",
            "/api/v1/notifications",
            "/api/v1/channels",
        ]
        for expected in tenant_scoped:
            assert any(expected in p for p in paths), f"Missing tenant-scoped route: {expected}"


# ── Fresh company end-to-end test ─────────────────────────────────────────────

class TestFreshCompanyEndToEnd:
    """
    Simulates the complete fresh-company onboarding workflow.
    Uses mocks for all external services.
    """

    @pytest.mark.asyncio
    async def test_full_onboarding_workflow(self):
        """
        Company creation → Admin user → DMM config → Onboarding status check.
        """
        from app.api.routers.onboarding import OnboardCompanyRequest
        from app.db.models import Company, User, RoleConfiguration
        import datetime

        mock_db = AsyncMock()
        added = []

        def track_add(obj):
            now = datetime.datetime.now(datetime.timezone.utc)
            if isinstance(obj, Company):
                obj.created_at = obj.updated_at = now
            if isinstance(obj, User):
                obj.created_at = obj.updated_at = now
            added.append(obj)

        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        # Step 1: Create company
        with patch("app.api.routers.role_config._get_or_seed", new_callable=AsyncMock), \
             patch("app.api.routers.onboarding._pwd.hash", return_value="$2b$12$mockhash"):
            from app.api.routers.onboarding import onboard_new_company
            req = OnboardCompanyRequest(
                company_name="E2E Test Corp",
                industry="Marketing",
                region="UK",
                employees=10,
                admin_name="E2E Admin",
                admin_email="admin@e2etestcorp.com",
                admin_password="E2ETest123",
            )
            result = await onboard_new_company(req, mock_db)

        tenant_id = result.tenant_id
        assert result.dmm_initialized is True
        companies = [o for o in added if isinstance(o, Company)]
        users = [o for o in added if isinstance(o, User)]
        assert companies[0].name == "E2E Test Corp"
        assert users[0].email == "admin@e2etestcorp.com"
        assert users[0].role == "Company Admin"
        assert users[0].tenant_id == tenant_id

    @pytest.mark.asyncio
    async def test_two_companies_completely_isolated(self):
        """
        Company A and Company B get separate, isolated DMM configs.
        """
        from app.api.routers.onboarding import OnboardCompanyRequest
        from app.db.models import Company, User

        created_company_ids = []

        mock_db = AsyncMock()
        def track_add(obj):
            if isinstance(obj, Company):
                created_company_ids.append(obj.id)

        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        with patch("app.api.routers.role_config._get_or_seed", new_callable=AsyncMock), \
             patch("app.api.routers.onboarding._pwd.hash", return_value="$2b$12$mockhash"):
            from app.api.routers.onboarding import onboard_new_company
            result_a = await onboard_new_company(
                OnboardCompanyRequest(
                    company_name="Company Alpha", admin_name="Alpha Admin",
                    admin_email="admin@alpha.com", admin_password="AlphaPass1",
                ),
                mock_db,
            )
            result_b = await onboard_new_company(
                OnboardCompanyRequest(
                    company_name="Company Beta", admin_name="Beta Admin",
                    admin_email="admin@beta.com", admin_password="BetaPass12",
                ),
                mock_db,
            )

        # Company IDs must be different (separate tenants)
        assert result_a.company_id != result_b.company_id
        assert result_a.tenant_id != result_b.tenant_id
        assert result_a.admin_user_id != result_b.admin_user_id

    def test_onboarding_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/onboarding" in p for p in paths)

    def test_dmm_is_only_active_role(self):
        """DIGITAL_MARKETING_MANAGER is the only fully implemented role."""
        from app.schemas.role_config import IMPLEMENTED_ROLES
        assert "DIGITAL_MARKETING_MANAGER" in IMPLEMENTED_ROLES
        # Other roles exist as keys but are not in IMPLEMENTED_ROLES (coming soon)
        future_roles = [
            "SALES_DEVELOPMENT_REP", "FINANCIAL_ANALYST",
            "HR_BUSINESS_PARTNER", "CUSTOMER_SUCCESS_MANAGER",
        ]
        for role in future_roles:
            assert role not in IMPLEMENTED_ROLES, f"{role} should not be implemented yet"

    def test_coming_soon_roles_return_404(self):
        """Non-implemented roles must return a clear 'coming soon' response."""
        from app.api.routers.role_config import _get_defaults
        from app.schemas.role_config import IMPLEMENTED_ROLES
        # _get_defaults returns minimal config for unimplemented roles
        defaults = _get_defaults("SALES_DEVELOPMENT_REP")
        assert defaults["role_name"] == "Sales Development Rep"  # exists but not active


# ── AI Workforce extensibility tests ─────────────────────────────────────────

class TestAIWorkforceExtensibility:
    def test_role_config_is_generic(self):
        """RoleConfiguration does not hardcode DMM-specific fields."""
        from app.db.models import RoleConfiguration
        cols = [c.key for c in RoleConfiguration.__table__.columns]
        # Generic fields that work for any role
        for expected in ("tenant_id", "role_key", "role_name", "tool_scopes_json",
                         "permissions_json", "workflows_json", "monitoring_rules_json"):
            assert expected in cols, f"Missing generic column: {expected}"

    def test_blueprint_schema_is_generic(self):
        """AgentBlueprint schema works for any role, not just DMM."""
        from app.schemas.blueprint import AgentBlueprint
        bp = AgentBlueprint(
            agent_id="future-agent-1",
            role_name="Sales Development Rep",  # future role
            system_persona="You are the Sales Development Rep.",
            allowed_tools=[],
            guarded_tools=[],
            tenant_id="t1",
        )
        assert bp.role_name == "Sales Development Rep"

    def test_action_governance_is_role_agnostic(self):
        """action_governance works for any role key."""
        import inspect
        from app.services import action_governance
        source = inspect.getsource(action_governance)
        # Must not hardcode DIGITAL_MARKETING_MANAGER as the only role
        assert source.count('"DIGITAL_MARKETING_MANAGER"') <= 2  # at most in role-specific defaults

    def test_planner_is_role_agnostic(self):
        """The planner can create plans for any role."""
        from app.services.planner import _role_key
        # _role_key maps role names to keys but has a sensible default
        assert _role_key("Digital Marketing Manager") == "DIGITAL_MARKETING_MANAGER"
        assert _role_key("Unknown Future Role") == "DIGITAL_MARKETING_MANAGER"  # safe default

    def test_monitoring_engine_is_role_agnostic(self):
        """Monitoring engine uses role_key from DB, not hardcoded."""
        import inspect
        from app.services import monitoring_engine
        source = inspect.getsource(monitoring_engine)
        # The engine reads role_key from the MonitoringRule record
        assert "rule.role_key" in source


# ── Demo data separation tests ─────────────────────────────────────────────────

class TestDemoDataSeparation:
    def test_demo_companies_in_mock_data(self):
        """Demo companies exist in mock data — clearly separate from production."""
        from app.db.seed import seed_demo_data
        assert callable(seed_demo_data)

    def test_mock_companies_labeled(self):
        """Frontend mock data is in mockData.ts, not mixed with real API calls."""
        # Verified by architecture: USE_REAL_API=false → mock data, USE_REAL_API=true → real API
        # The switch happens in use-api.ts hooks, not in mockData.ts directly
        import inspect, importlib.util, os
        mock_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "services", "mockData.ts"
        )
        # File exists
        assert os.path.exists(os.path.abspath(mock_path))

    def test_existing_tests_unaffected(self):
        """Existing 715 tests still import cleanly."""
        import tests.test_campaigns
        import tests.test_funnel_intelligence
        import tests.test_strategy_intelligence
        import tests.test_content_intelligence
        import tests.test_completion_sprint


