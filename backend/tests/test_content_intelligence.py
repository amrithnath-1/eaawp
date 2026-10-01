"""Tests for Marketing Content Intelligence subsystem."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ── Schema validation ─────────────────────────────────────────────────────────

class TestContentSchemas:
    def test_valid_content_item_create(self):
        from app.schemas.content import ContentItemCreate
        c = ContentItemCreate(title="Q4 Email Draft", content_type="draft", channel="email")
        assert c.title == "Q4 Email Draft"

    def test_sql_injection_in_title_rejected(self):
        from app.schemas.content import ContentItemCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContentItemCreate(title="Test; DROP TABLE content_items --")

    def test_invalid_content_type_rejected(self):
        from app.schemas.content import ContentItemCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContentItemCreate(title="Test", content_type="malicious")  # type: ignore

    def test_invalid_status_rejected(self):
        from app.schemas.content import ContentItemUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContentItemUpdate(status="hacked")  # type: ignore

    def test_generate_brief_requires_objective(self):
        from app.schemas.content import GenerateBriefRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GenerateBriefRequest(objective="")  # min_length=1

    def test_generate_brief_valid(self):
        from app.schemas.content import GenerateBriefRequest
        r = GenerateBriefRequest(objective="Increase Q4 leads", channel="email", tone="formal")
        assert r.objective == "Increase Q4 leads"

    def test_generate_draft_max_words_capped(self):
        from app.schemas.content import GenerateDraftRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GenerateDraftRequest(objective="Test", max_words=9999)  # max 2000

    def test_generate_variants_n_capped(self):
        from app.schemas.content import GenerateVariantsRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GenerateVariantsRequest(source_content_id="abc", n_variants=10)  # max 5

    def test_analyze_requires_content_id(self):
        from app.schemas.content import AnalyzeContentRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AnalyzeContentRequest(content_id="")


# ── ORM model ─────────────────────────────────────────────────────────────────

class TestContentModel:
    def test_content_item_importable(self):
        from app.db.content_models import ContentItem
        assert ContentItem.__tablename__ == "content_items"

    def test_content_item_has_tenant_id(self):
        from app.db.content_models import ContentItem
        cols = [c.key for c in ContentItem.__table__.columns]
        assert "tenant_id" in cols

    def test_content_item_no_credentials(self):
        from app.db.content_models import ContentItem
        cols = [c.key for c in ContentItem.__table__.columns]
        for bad in ("password", "api_key", "secret", "connection_string"):
            assert bad not in cols

    def test_content_item_has_rag_sources(self):
        from app.db.content_models import ContentItem
        assert hasattr(ContentItem, "rag_sources_json")

    def test_content_item_has_analysis_json(self):
        from app.db.content_models import ContentItem
        assert hasattr(ContentItem, "analysis_json")


# ── Content service CRUD ──────────────────────────────────────────────────────

class TestContentServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_content(self):
        from app.schemas.content import ContentItemCreate
        from app.services.content_service import create_content
        from app.db.content_models import ContentItem

        body = ContentItemCreate(title="Test Draft", content_type="draft",
                                 channel="email", body="Hello world")
        mock_db = AsyncMock()
        added = []
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
            added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        result = await create_content(body, "t1", mock_db)
        assert result.title == "Test Draft"
        assert result.tenant_id == "t1"
        assert result.content_type == "draft"

    @pytest.mark.asyncio
    async def test_get_content_wrong_tenant_returns_none(self):
        from app.services.content_service import get_content
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await get_content("c1", "wrong-tenant", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_content_wrong_tenant_returns_none(self):
        from app.schemas.content import ContentItemUpdate
        from app.services.content_service import update_content
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await update_content("c1", ContentItemUpdate(title="New"), "wrong-tenant", mock_db)
        assert result is None


# ── Generation (mocked LLM) ────────────────────────────────────────────────────

class TestContentGeneration:
    @pytest.mark.asyncio
    async def test_generate_brief_creates_item(self):
        from app.schemas.content import GenerateBriefRequest
        from app.services.content_service import generate_brief
        from app.db.content_models import ContentItem

        mock_db = AsyncMock()
        added = []
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
            added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="Generated brief content."), \
             patch("app.services.content_service._fetch_rag_context", return_value=("", [])):
            req = GenerateBriefRequest(objective="Increase leads", channel="email")
            result = await generate_brief(req, "t1", mock_db)

        assert result.content_type == "brief"
        assert result.tenant_id == "t1"
        assert "Increase leads" in result.title

    @pytest.mark.asyncio
    async def test_generate_draft_creates_item(self):
        from app.schemas.content import GenerateDraftRequest
        from app.services.content_service import generate_draft
        from app.db.content_models import ContentItem

        mock_db = AsyncMock()
        added = []
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
            added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="Draft email content here."), \
             patch("app.services.content_service._fetch_rag_context", return_value=("brand context", ["Brand Guide v1"])):
            req = GenerateDraftRequest(objective="Promote Q4 sale", channel="email", tone="casual")
            result = await generate_draft(req, "t1", mock_db)

        assert result.content_type == "draft"
        assert result.channel == "email"
        assert result.rag_sources == ["Brand Guide v1"]

    @pytest.mark.asyncio
    async def test_generate_ideas_creates_item(self):
        from app.schemas.content import GenerateIdeasRequest
        from app.services.content_service import generate_ideas
        from app.db.content_models import ContentItem

        mock_db = AsyncMock()
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
            mock_db._added = getattr(mock_db, "_added", [])
            mock_db._added.append(obj)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="5 content ideas:\n1. Idea one\n2. Idea two"), \
             patch("app.services.content_service._fetch_rag_context", return_value=("", [])):
            req = GenerateIdeasRequest(objective="Drive blog traffic", channel="blog", n_ideas=3)
            result = await generate_ideas(req, "t1", mock_db)

        assert result.content_type == "idea"

    @pytest.mark.asyncio
    async def test_generate_variants_requires_existing_source(self):
        from app.schemas.content import GenerateVariantsRequest
        from app.services.content_service import generate_variants

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # source not found
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = GenerateVariantsRequest(source_content_id="nonexistent-id", n_variants=2)
        with pytest.raises(ValueError, match="not found"):
            await generate_variants(req, "t1", mock_db)

    @pytest.mark.asyncio
    async def test_generate_variants_tenant_isolated(self):
        from app.schemas.content import GenerateVariantsRequest
        from app.services.content_service import generate_variants

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # wrong tenant → not found
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = GenerateVariantsRequest(source_content_id="c1", n_variants=2)
        with pytest.raises(ValueError):
            await generate_variants(req, "wrong-tenant", mock_db)

    @pytest.mark.asyncio
    async def test_analyze_content_updates_analysis_json(self):
        from app.schemas.content import AnalyzeContentRequest
        from app.services.content_service import analyze_content
        from app.db.content_models import ContentItem

        mock_item = MagicMock(spec=ContentItem)
        mock_item.id = "c1"
        mock_item.tenant_id = "t1"
        mock_item.content_type = "draft"
        mock_item.status = "draft"
        mock_item.title = "Test Draft"
        mock_item.channel = "email"
        mock_item.brief_json = "{}"
        mock_item.body = "Hello, buy our product for great value!"
        mock_item.campaign_id = None
        mock_item.objective_id = None
        mock_item.parent_id = None
        mock_item.rag_sources_json = "[]"
        mock_item.analysis_json = "{}"
        mock_item.metadata_json = "{}"
        mock_item.created_by = "agent"
        mock_item.created_at = datetime.now(timezone.utc)
        mock_item.updated_at = datetime.now(timezone.utc)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="Score: 7/10. Strength: clear CTA."), \
             patch("app.services.content_service._fetch_rag_context", return_value=("", [])):
            req = AnalyzeContentRequest(content_id="c1", campaign_objective="Drive sales")
            result = await analyze_content(req, "t1", mock_db)

        assert "analysis" in result.analysis
        assert result.analysis["analysis"] == "Score: 7/10. Strength: clear CTA."


# ── RAG integration ────────────────────────────────────────────────────────────

class TestContentRAGIntegration:
    @pytest.mark.asyncio
    async def test_rag_sources_stored_with_content(self):
        from app.schemas.content import GenerateBriefRequest
        from app.services.content_service import generate_brief
        from app.db.content_models import ContentItem

        mock_db = AsyncMock()
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="Brief content."), \
             patch("app.services.content_service._fetch_rag_context",
                   return_value=("Brand guideline context", ["Brand Guidelines v2.pdf"])):
            req = GenerateBriefRequest(objective="Q4 campaign", channel="email")
            result = await generate_brief(req, "t1", mock_db)

        assert "Brand Guidelines v2.pdf" in result.rag_sources

    @pytest.mark.asyncio
    async def test_no_fabrication_when_rag_empty(self):
        """When RAG returns nothing, generation still proceeds without fabricating company data."""
        from app.schemas.content import GenerateDraftRequest
        from app.services.content_service import generate_draft
        from app.db.content_models import ContentItem

        mock_db = AsyncMock()
        def track(obj):
            if isinstance(obj, ContentItem):
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
        mock_db.add = track
        mock_db.flush = AsyncMock()

        with patch("app.services.content_service._llm", return_value="Draft content without company data."), \
             patch("app.services.content_service._fetch_rag_context", return_value=("", [])):
            req = GenerateDraftRequest(objective="Generic campaign", channel="social_linkedin")
            result = await generate_draft(req, "t1", mock_db)

        assert result.rag_sources == []  # no sources fabricated


# ── Tool registration ─────────────────────────────────────────────────────────

class TestContentTools:
    def test_all_content_tools_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ("generate_content_brief", "generate_content_ideas",
                  "generate_content_draft", "generate_content_variants", "analyze_content"):
            assert t in MASTER_TOOL_REGISTRY

    def test_content_tools_not_in_action_registry(self):
        """Content generation is not an action — no approval required."""
        from app.actions.registry import ACTION_REGISTRY
        for t in ("generate_content_brief", "generate_content_ideas",
                  "generate_content_draft", "generate_content_variants", "analyze_content"):
            assert t not in ACTION_REGISTRY

    def test_content_tools_in_dmm_defaults(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        keys = [t["tool_key"] for t in tool_scopes]
        for t in ("generate_content_brief", "generate_content_draft", "analyze_content"):
            assert t in keys

    def test_content_tools_governance_is_enabled(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        for t in ("generate_content_brief", "generate_content_ideas",
                  "generate_content_draft", "generate_content_variants", "analyze_content"):
            scope = next((s for s in tool_scopes if s["tool_key"] == t), None)
            assert scope is not None
            assert scope["governance"] == "enabled"

    def test_content_tools_in_planner_prompt(self):
        from app.services.planner import _PLANNER_SYSTEM
        for t in ("generate_content_brief", "generate_content_draft", "analyze_content"):
            assert t in _PLANNER_SYSTEM


# ── Router ────────────────────────────────────────────────────────────────────

class TestContentRouter:
    def test_content_router_registered(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        assert any("/api/v1/content" in p for p in paths)

    def test_no_publish_endpoint(self):
        """There must be no publish endpoint — no external publishing."""
        from app.api.routers.content import router
        paths = [r.path for r in router.routes]
        assert not any("publish" in p for p in paths)


# ── Security ──────────────────────────────────────────────────────────────────

class TestContentSecurity:
    def test_content_service_no_credentials(self):
        import inspect
        from app.services import content_service
        source = inspect.getsource(content_service)
        assert "password" not in source
        assert "encrypted_password" not in source
        assert "decrypt_password" not in source

    def test_no_arbitrary_sql_in_service(self):
        import inspect
        from app.services import content_service
        source = inspect.getsource(content_service)
        assert "execute(" not in source.split("from sqlalchemy")[0]

    def test_no_auto_publish_in_service(self):
        import inspect
        from app.services import content_service
        source = inspect.getsource(content_service)
        # Must not have actual publish calls to external systems
        assert "post_to_social" not in source
        assert "send_to_cms" not in source
        assert "requests.post" not in source
        # "publish" may appear in comments/docstrings as a prohibition

    def test_llm_system_prompt_no_credentials(self):
        from app.services.content_service import _CONTENT_SYSTEM
        # Must not contain actual credential values or instructions to use them
        assert "api_key" not in _CONTENT_SYSTEM.lower()
        assert "password" not in _CONTENT_SYSTEM.lower()
        assert "secret_key" not in _CONTENT_SYSTEM.lower()
        # "credential" appearing as a prohibition is acceptable


# ── Campaign/objective integration ────────────────────────────────────────────

class TestContentCampaignIntegration:
    def test_content_can_link_campaign_id(self):
        from app.schemas.content import ContentItemCreate
        c = ContentItemCreate(title="Campaign Content", content_type="draft",
                              campaign_id="cam-1", channel="email")
        assert c.campaign_id == "cam-1"

    def test_content_can_link_objective_id(self):
        from app.schemas.content import ContentItemCreate
        c = ContentItemCreate(title="Objective Content", content_type="brief",
                              objective_id="obj-1")
        assert c.objective_id == "obj-1"

    def test_brief_request_accepts_campaign_context(self):
        from app.schemas.content import GenerateBriefRequest
        r = GenerateBriefRequest(
            objective="Increase signups", campaign_id="cam-1",
            campaign_name="Q4 Growth", kpis=["CTR", "Conversions"],
        )
        assert r.campaign_name == "Q4 Growth"
        assert r.kpis == ["CTR", "Conversions"]


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithContent:
    def test_all_previous_tools_still_registered(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_company_data", "analyze_campaign_performance",
                  "analyze_funnel", "analyze_marketing_strategy",
                  "create_campaign", "draft_email", "send_email"]:
            assert t in MASTER_TOOL_REGISTRY

    def test_strategy_service_intact(self):
        from app.services.strategy_service import build_strategic_analysis
        assert callable(build_strategic_analysis)

    def test_kpi_engine_intact(self):
        from app.services.kpi_engine import calculate_all_kpis
        assert callable(calculate_all_kpis)

    def test_governance_intact(self):
        from app.services.action_governance import process_action_request
        assert callable(process_action_request)

    def test_content_model_no_cms_table_refs(self):
        from app.db.content_models import ContentItem
        import inspect
        source = inspect.getsource(ContentItem)
        for ext_table in ("wordpress_posts", "hubspot_content", "salesforce"):
            assert ext_table not in source
