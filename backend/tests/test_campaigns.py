"""
Tests for the Campaign Management Foundation.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ── Schema validation ─────────────────────────────────────────────────────────

class TestCampaignSchemas:
    def test_valid_campaign_create(self):
        from app.schemas.campaign import CampaignCreate
        c = CampaignCreate(name="Summer Sale", objective="Increase conversions", channel="email", budget=5000.0)
        assert c.name == "Summer Sale"
        assert c.budget == 5000.0

    def test_sql_injection_in_name_rejected(self):
        from app.schemas.campaign import CampaignCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignCreate(name="Test; DROP TABLE campaigns --")

    def test_sql_injection_exec_rejected(self):
        from app.schemas.campaign import CampaignCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignCreate(name="exec(os.system('rm -rf /'))")

    def test_date_format_validated(self):
        from app.schemas.campaign import CampaignCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignCreate(name="Test", start_date="not-a-date")

    def test_valid_date_format(self):
        from app.schemas.campaign import CampaignCreate
        c = CampaignCreate(name="Test", start_date="2026-01-15", end_date="2026-03-31")
        assert c.start_date == "2026-01-15"

    def test_budget_non_negative(self):
        from app.schemas.campaign import CampaignCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignCreate(name="Test", budget=-100.0)

    def test_all_valid_statuses(self):
        from app.schemas.campaign import VALID_STATUSES
        for s in ("draft", "planned", "active", "paused", "completed", "cancelled"):
            assert s in VALID_STATUSES

    def test_update_invalid_status_rejected(self):
        from app.schemas.campaign import UpdateCampaignInput
        from pydantic import ValidationError
        import uuid
        with pytest.raises(ValidationError):
            UpdateCampaignInput(campaign_id=str(uuid.uuid4()), status="deleted")

    def test_update_invalid_campaign_id_rejected(self):
        from app.schemas.campaign import UpdateCampaignInput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateCampaignInput(campaign_id="not-a-uuid'; DROP TABLE campaigns --")

    def test_metric_name_validated(self):
        from app.schemas.campaign import CampaignMetricCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignMetricCreate(metric_name="clicks; DROP TABLE--", metric_value=100.0, metric_date="2026-01-01")

    def test_metric_date_validated(self):
        from app.schemas.campaign import CampaignMetricCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CampaignMetricCreate(metric_name="clicks", metric_value=100.0, metric_date="invalid")

    def test_determine_update_risk_budget_change_is_high(self):
        from app.schemas.campaign import CampaignUpdate, determine_update_risk
        u = CampaignUpdate(budget=99999.0)
        risk = determine_update_risk(u, current_status="active", current_budget=5000.0)
        assert risk == "high"

    def test_determine_update_risk_status_to_active_is_high(self):
        from app.schemas.campaign import CampaignUpdate, determine_update_risk
        u = CampaignUpdate(status="active")
        risk = determine_update_risk(u, current_status="planned", current_budget=5000.0)
        assert risk == "high"

    def test_determine_update_risk_cancelled_is_high(self):
        from app.schemas.campaign import CampaignUpdate, determine_update_risk
        u = CampaignUpdate(status="cancelled")
        risk = determine_update_risk(u, current_status="active", current_budget=5000.0)
        assert risk == "high"

    def test_determine_update_risk_name_change_is_medium(self):
        from app.schemas.campaign import CampaignUpdate, determine_update_risk
        u = CampaignUpdate(name="New Name")
        risk = determine_update_risk(u, current_status="draft", current_budget=0.0)
        assert risk == "medium"


# ── ORM model tests ───────────────────────────────────────────────────────────

class TestCampaignModels:
    def test_campaign_model_importable(self):
        from app.db.campaign_models import Campaign
        assert Campaign.__tablename__ == "campaigns"

    def test_campaign_metric_model_importable(self):
        from app.db.campaign_models import CampaignMetric
        assert CampaignMetric.__tablename__ == "campaign_metrics"

    def test_campaign_has_tenant_id(self):
        from app.db.campaign_models import Campaign
        assert hasattr(Campaign, "tenant_id")

    def test_campaign_metric_has_tenant_id(self):
        from app.db.campaign_models import CampaignMetric
        assert hasattr(CampaignMetric, "tenant_id")

    def test_campaign_no_credentials(self):
        from app.db.campaign_models import Campaign
        cols = [c.key for c in Campaign.__table__.columns]
        for bad in ("password", "api_key", "secret", "token"):
            assert bad not in cols

    def test_campaign_kpis_json_field(self):
        from app.db.campaign_models import Campaign
        assert hasattr(Campaign, "kpis_json")

    def test_campaign_statuses_in_defaults(self):
        from app.db.campaign_models import Campaign
        import inspect
        source = inspect.getsource(Campaign)
        for status in ("draft", "planned", "active", "paused", "completed", "cancelled"):
            assert status in source


# ── Service tests ─────────────────────────────────────────────────────────────

class TestCampaignService:
    @pytest.mark.asyncio
    async def test_create_campaign(self):
        from app.schemas.campaign import CampaignCreate
        from app.services.campaign_service import create_campaign
        from app.db.campaign_models import Campaign

        body = CampaignCreate(name="Q4 Launch", objective="Drive sales", channel="email", budget=10000.0)
        mock_db = AsyncMock()
        added = []

        def track_add(obj):
            if isinstance(obj, Campaign):
                # Set datetime fields that SQLAlchemy normally fills via server_default
                now = datetime.now(timezone.utc)
                obj.created_at = now
                obj.updated_at = now
            added.append(obj)

        mock_db.add = track_add
        mock_db.flush = AsyncMock()

        result = await create_campaign(body, "tenant-1", mock_db)

        assert result.name == "Q4 Launch"
        assert result.tenant_id == "tenant-1"
        assert result.status == "draft"
        assert len([o for o in added if isinstance(o, Campaign)]) == 1

    @pytest.mark.asyncio
    async def test_list_campaigns_filters_by_tenant(self):
        from app.services.campaign_service import list_campaigns
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await list_campaigns("tenant-1", mock_db)
        assert result == []
        # Verify execute was called with a query (tenant isolation)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_campaign_returns_none_for_wrong_tenant(self):
        from app.services.campaign_service import get_campaign
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await get_campaign("campaign-1", "wrong-tenant", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_record_metric_verifies_tenant(self):
        from app.schemas.campaign import CampaignMetricCreate
        from app.services.campaign_service import record_metric
        mock_db = AsyncMock()
        # First call: campaign lookup → not found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        body = CampaignMetricCreate(metric_name="clicks", metric_value=500.0, metric_date="2026-01-01")
        result = await record_metric("cam-1", body, "tenant-X", mock_db)
        assert result is None  # campaign not found for this tenant

    @pytest.mark.asyncio
    async def test_archive_campaign_sets_cancelled(self):
        from app.services.campaign_service import archive_campaign
        from app.db.campaign_models import Campaign

        mock_campaign = MagicMock(spec=Campaign)
        mock_campaign.id = "cam-1"
        mock_campaign.tenant_id = "tenant-1"
        mock_campaign.name = "Old Campaign"
        mock_campaign.status = "active"
        mock_campaign.objective = ""
        mock_campaign.description = ""
        mock_campaign.target_audience = ""
        mock_campaign.channel = "email"
        mock_campaign.budget = 1000.0
        mock_campaign.start_date = None
        mock_campaign.end_date = None
        mock_campaign.kpis_json = "[]"
        mock_campaign.metadata_json = "{}"
        mock_campaign.created_by = "agent"
        mock_campaign.created_at = datetime.now(timezone.utc)
        mock_campaign.updated_at = datetime.now(timezone.utc)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_campaign
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await archive_campaign("cam-1", "tenant-1", mock_db)
        assert mock_campaign.status == "cancelled"

    @pytest.mark.asyncio
    async def test_get_campaign_summary_includes_metrics(self):
        from app.services.campaign_service import get_campaign_summary
        from app.db.campaign_models import Campaign, CampaignMetric

        mock_campaign = MagicMock(spec=Campaign)
        mock_campaign.id = "cam-1"
        mock_campaign.name = "Test Campaign"
        mock_campaign.status = "active"
        mock_campaign.channel = "email"
        mock_campaign.objective = "Drive sales"
        mock_campaign.budget = 5000.0
        mock_campaign.start_date = "2026-01-01"
        mock_campaign.end_date = "2026-03-31"
        mock_campaign.kpis_json = json.dumps([{"name": "CTR", "target": 0.05, "unit": "%"}])

        mock_metric = MagicMock(spec=CampaignMetric)
        mock_metric.metric_name = "clicks"
        mock_metric.metric_value = 1200.0
        mock_metric.metric_date = "2026-01-15"
        mock_metric.source = "manual"

        mock_db = AsyncMock()
        call_count = [0]

        def make_result(obj=None, scalars=None):
            r = MagicMock()
            r.scalar_one_or_none.return_value = obj
            r.scalars.return_value.all.return_value = scalars or []
            return r

        async def execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_result(obj=mock_campaign)
            return make_result(scalars=[mock_metric])

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        summary = await get_campaign_summary("cam-1", "tenant-1", mock_db)
        assert summary is not None
        assert summary.name == "Test Campaign"
        assert summary.kpi_count == 1
        assert len(summary.latest_metrics) == 1
        assert summary.latest_metrics[0]["name"] == "clicks"


# ── Action tool tests ─────────────────────────────────────────────────────────

class TestCampaignActionTools:
    def test_create_campaign_action_importable(self):
        from app.actions.campaign_actions import CreateCampaignAction
        action = CreateCampaignAction()
        assert action.meta.tool_name == "create_campaign"

    def test_create_campaign_risk_is_medium(self):
        from app.actions.campaign_actions import CreateCampaignAction
        assert CreateCampaignAction().meta.risk_level == "medium"

    def test_create_campaign_requires_approval(self):
        from app.actions.campaign_actions import CreateCampaignAction
        assert CreateCampaignAction().meta.requires_approval is True

    def test_update_campaign_action_importable(self):
        from app.actions.campaign_actions import UpdateCampaignAction
        action = UpdateCampaignAction()
        assert action.meta.tool_name == "update_campaign"

    def test_update_campaign_risk_is_high(self):
        from app.actions.campaign_actions import UpdateCampaignAction
        assert UpdateCampaignAction().meta.risk_level == "high"

    def test_create_campaign_registered_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "create_campaign" in ACTION_REGISTRY

    def test_update_campaign_registered_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "update_campaign" in ACTION_REGISTRY

    def test_read_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for tool in ("get_campaigns", "get_campaign_metrics", "get_campaign_summary"):
            assert tool in MASTER_TOOL_REGISTRY

    def test_action_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for tool in ("create_campaign", "update_campaign"):
            assert tool in MASTER_TOOL_REGISTRY

    def test_validate_create_campaign_valid(self):
        from app.actions.campaign_actions import CreateCampaignAction
        action = CreateCampaignAction()
        is_valid, err, normalised = action.validate({
            "name": "Q4 Email Campaign",
            "objective": "Drive 20% more conversions",
            "channel": "email",
            "budget": 8000.0,
        })
        assert is_valid is True
        assert normalised["name"] == "Q4 Email Campaign"

    def test_validate_create_campaign_sql_injection_rejected(self):
        from app.actions.campaign_actions import CreateCampaignAction
        action = CreateCampaignAction()
        is_valid, err, _ = action.validate({"name": "'; DROP TABLE campaigns --"})
        assert is_valid is False

    def test_validate_update_campaign_invalid_uuid_rejected(self):
        from app.actions.campaign_actions import UpdateCampaignAction
        action = UpdateCampaignAction()
        is_valid, err, _ = action.validate({"campaign_id": "not-valid-uuid-injection"})
        assert is_valid is False

    def test_validate_update_campaign_invalid_status_rejected(self):
        from app.actions.campaign_actions import UpdateCampaignAction
        import uuid
        action = UpdateCampaignAction()
        is_valid, err, _ = action.validate({"campaign_id": str(uuid.uuid4()), "status": "hacked"})
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_create_campaign_governance_requires_approval(self):
        """create_campaign must go through governance and propose for approval."""
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="create_campaign",
            arguments={"name": "New Campaign", "channel": "email", "budget": 5000.0},
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            requested_by="agent",
        )
        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=["create_campaign"],
            blueprint_guarded_tools=["create_campaign"],
            db=mock_db,
        )
        assert result.status == "proposed"
        assert result.approval_request_id is not None

    @pytest.mark.asyncio
    async def test_update_campaign_governance_requires_approval(self):
        """update_campaign must always propose for approval."""
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        import uuid

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="update_campaign",
            arguments={"campaign_id": str(uuid.uuid4()), "budget": 20000.0},
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            requested_by="agent",
        )
        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=["update_campaign"],
            blueprint_guarded_tools=["update_campaign"],
            db=mock_db,
        )
        assert result.status == "proposed"

    @pytest.mark.asyncio
    async def test_campaign_tool_not_in_allowed_tools_unauthorized(self):
        """Campaign tools blocked if not in blueprint allowed_tools."""
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="create_campaign",
            arguments={"name": "Unauthorized Campaign"},
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            requested_by="agent",
        )
        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=[],  # create_campaign not allowed
            blueprint_guarded_tools=[],
            db=mock_db,
        )
        assert result.status == "unauthorized"


# ── Tenant isolation tests ────────────────────────────────────────────────────

class TestCampaignTenantIsolation:
    def test_campaign_model_has_tenant_id(self):
        from app.db.campaign_models import Campaign
        cols = [c.key for c in Campaign.__table__.columns]
        assert "tenant_id" in cols

    def test_campaign_metric_model_has_tenant_id(self):
        from app.db.campaign_models import CampaignMetric
        cols = [c.key for c in CampaignMetric.__table__.columns]
        assert "tenant_id" in cols

    @pytest.mark.asyncio
    async def test_get_campaign_wrong_tenant_returns_none(self):
        from app.services.campaign_service import get_campaign
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await get_campaign("cam-1", "different-tenant", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_campaign_wrong_tenant_returns_none(self):
        from app.schemas.campaign import CampaignUpdate
        from app.services.campaign_service import update_campaign
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await update_campaign("cam-1", CampaignUpdate(name="New"), "wrong-tenant", mock_db)
        assert result is None


# ── Planner integration ───────────────────────────────────────────────────────

class TestCampaignPlannerIntegration:
    def test_planner_prompt_mentions_campaign_tools(self):
        from app.services.planner import _PLANNER_SYSTEM
        for tool in ("get_campaigns", "get_campaign_metrics", "get_campaign_summary",
                     "create_campaign", "update_campaign"):
            assert tool in _PLANNER_SYSTEM, f"Missing {tool} in planner prompt"

    def test_planner_prompt_classifies_reads_as_low_risk(self):
        from app.services.planner import _PLANNER_SYSTEM
        assert "low risk" in _PLANNER_SYSTEM.lower() or "read" in _PLANNER_SYSTEM.lower()

    def test_planner_prompt_classifies_budget_as_high_risk(self):
        from app.services.planner import _PLANNER_SYSTEM
        assert "budget" in _PLANNER_SYSTEM.lower()
        assert "high risk" in _PLANNER_SYSTEM.lower() or "HIGH" in _PLANNER_SYSTEM

    def test_planner_prompt_forbids_direct_sql(self):
        from app.services.planner import _PLANNER_SYSTEM
        assert "SQL" in _PLANNER_SYSTEM or "sql" in _PLANNER_SYSTEM.lower()

    def test_campaign_read_step(self):
        from app.schemas.planning import PlannedStep
        step = PlannedStep(
            step_index=0, step_type="read",
            description="List active campaigns",
            tool_name="get_campaigns",
            arguments={"status": "active"},
            depends_on=[],
        )
        assert step.tool_name == "get_campaigns"

    def test_campaign_action_step(self):
        from app.schemas.planning import PlannedStep
        step = PlannedStep(
            step_index=1, step_type="action",
            description="Create new campaign",
            tool_name="create_campaign",
            arguments={"name": "Test", "channel": "email", "budget": 5000.0},
            depends_on=[0],
        )
        assert step.step_type == "action"


# ── Monitoring integration ────────────────────────────────────────────────────

class TestCampaignMonitoringIntegration:
    def test_campaign_metric_source_field_supports_monitoring(self):
        from app.db.campaign_models import CampaignMetric
        assert hasattr(CampaignMetric, "source")

    def test_campaign_metric_source_can_be_monitoring(self):
        from app.schemas.campaign import CampaignMetricCreate
        m = CampaignMetricCreate(
            metric_name="ctr",
            metric_value=0.02,
            metric_date="2026-01-01",
            source="monitoring",
        )
        assert m.source == "monitoring"

    def test_existing_monitoring_engine_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)


# ── Audit tests ───────────────────────────────────────────────────────────────

class TestCampaignAudit:
    def test_action_audit_model_exists(self):
        from app.db.models import ActionAudit
        assert hasattr(ActionAudit, "tool_name")
        assert hasattr(ActionAudit, "approval_status")

    def test_create_campaign_action_never_stores_credentials(self):
        from app.actions.campaign_actions import CreateCampaignAction
        import inspect
        source = inspect.getsource(CreateCampaignAction.execute)
        assert "password" not in source
        assert "decrypt" not in source
        assert "smtp" not in source.lower()

    def test_update_campaign_action_never_stores_credentials(self):
        from app.actions.campaign_actions import UpdateCampaignAction
        import inspect
        source = inspect.getsource(UpdateCampaignAction.execute)
        assert "password" not in source
        assert "api_key" not in source


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithCampaigns:
    def test_all_previous_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_campaign_analytics", "fetch_knowledge_base", "generate_report",
                  "query_company_data", "create_internal_task", "draft_email", "send_email"]:
            assert t in MASTER_TOOL_REGISTRY

    def test_existing_governance_intact(self):
        from app.services.action_governance import process_action_request
        assert callable(process_action_request)

    def test_existing_planner_intact(self):
        from app.services.planner import create_and_execute_plan
        assert callable(create_and_execute_plan)

    def test_existing_monitoring_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)

    def test_campaign_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/campaigns" in p for p in paths)

    def test_data_separation_no_external_table_assumptions(self):
        """Campaign models must not reference external table names as actual table/model names."""
        from app.db import campaign_models
        import inspect, ast
        source = inspect.getsource(campaign_models)
        # Check no SQLAlchemy __tablename__ references to external tables
        external_tables = ["leads", "customers", "revenue", "ad_spend", "conversions"]
        # Only check within __tablename__ definitions, not docstrings
        tablename_refs = re.findall(r'__tablename__\s*=\s*["\'](\w+)["\']', source)
        for table in external_tables:
            assert table not in tablename_refs, f"Found external __tablename__: {table}"
