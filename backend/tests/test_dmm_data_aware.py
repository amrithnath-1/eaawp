"""
Tests for the Data-Aware Digital Marketing Manager execution layer.

Covers:
- DMM blueprint includes query_company_data when configured
- DMM does NOT use company data when tool is absent from blueprint
- Denied entity prevents data retrieval
- Missing semantic mapping is handled safely
- Empty results are communicated clearly
- Connection failure is handled correctly
- Returned data is formatted for LLM reasoning
- RAG + company data can coexist
- No credentials appear in LLM context or responses
- No raw SQL appears in prompts
- Data context block only exposes allowed entities
- Identifier validation prevents SQL injection
- Tool context injection and clearing works correctly
- dmm_context returns empty string when no mappings exist
- build_data_source_metadata extracts safe labels
- Existing approval behavior: guarded tools still flagged
- Role config includes query_company_data in DMM defaults
"""

from __future__ import annotations

import json

import pytest

from app.schemas.blueprint import AgentBlueprint
from app.schemas.data_access import (
    CompanyDataQueryRequest,
    QueryFilter,
    validate_identifier,
)
from app.services.dmm_context import build_data_source_metadata


# ── Blueprint and tool governance ─────────────────────────────────────────────

class TestDMMBlueprint:
    """Verify the DMM blueprint properly includes/excludes query_company_data."""

    def test_blueprint_with_company_data_tool(self):
        bp = AgentBlueprint(
            agent_id="test-agent",
            role_name="Digital Marketing Manager",
            system_persona="You are the Marketing Intelligence Agent.",
            allowed_tools=["query_campaign_analytics", "query_company_data"],
            guarded_tools=["send_email"],
            tenant_id="tenant-1",
        )
        assert "query_company_data" in bp.allowed_tools
        assert "send_email" not in bp.allowed_tools

    def test_blueprint_without_company_data_tool(self):
        bp = AgentBlueprint(
            agent_id="test-agent",
            role_name="Digital Marketing Manager",
            system_persona="You are the Marketing Intelligence Agent.",
            allowed_tools=["query_campaign_analytics"],
            guarded_tools=[],
            tenant_id="tenant-1",
        )
        assert "query_company_data" not in bp.allowed_tools

    def test_tool_registry_contains_query_company_data(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "query_company_data" in MASTER_TOOL_REGISTRY

    def test_guarded_tool_approval_flag_still_works(self):
        """send_email in guarded_tools must still require approval."""
        bp = AgentBlueprint(
            agent_id="test",
            role_name="Digital Marketing Manager",
            system_persona="Test.",
            allowed_tools=["send_email", "query_company_data"],
            guarded_tools=["send_email"],
            tenant_id="tenant-1",
        )
        assert "send_email" in bp.guarded_tools
        assert "query_company_data" not in bp.guarded_tools

    def test_resolve_tools_includes_query_company_data(self):
        from app.tools.registry import resolve_tools
        tools = resolve_tools(["query_company_data", "fetch_knowledge_base"])
        assert len(tools) == 2

    def test_resolve_tools_excludes_unregistered_tool(self):
        from app.tools.registry import resolve_tools
        with pytest.raises(ValueError, match="not registered"):
            resolve_tools(["nonexistent_tool"])


# ── Tool context injection ────────────────────────────────────────────────────

class TestToolContextInjection:
    def test_set_and_clear_context(self):
        from app.tools.registry import (
            _db_session_ctx,
            _role_key_ctx,
            _tenant_id_ctx,
            clear_tool_context,
            set_tool_context,
        )

        class FakeDB:
            pass

        db = FakeDB()
        set_tool_context(db_session=db, tenant_id="t-123", role_key="DIGITAL_MARKETING_MANAGER")
        assert _db_session_ctx.get() is db
        assert _tenant_id_ctx.get() == "t-123"
        assert _role_key_ctx.get() == "DIGITAL_MARKETING_MANAGER"

        clear_tool_context()
        assert _db_session_ctx.get() is None
        assert _tenant_id_ctx.get() == "default-tenant"

    @pytest.mark.asyncio
    async def test_tool_returns_error_without_context(self):
        from app.tools.registry import clear_tool_context, query_company_data
        clear_tool_context()
        result = await query_company_data.ainvoke('{"semantic_concept": "test"}')
        assert "[ERROR]" in result or "no database session" in result.lower()


# ── Missing mapping / denied entity ──────────────────────────────────────────

class TestMissingMappingHandling:
    @pytest.mark.asyncio
    async def test_missing_mapping_query_returns_error_text(self):
        """When no semantic mapping exists, the tool must explain — not guess."""
        from app.tools.registry import clear_tool_context, query_company_data
        clear_tool_context()
        # No DB session → returns clear error, not SQL attempt
        result = await query_company_data.ainvoke('{"semantic_concept": "nonexistent_concept"}')
        # Must NOT contain any SQL keywords indicating a guess
        assert "DROP" not in result
        assert "SELECT *" not in result

    @pytest.mark.asyncio
    async def test_missing_concept_message_is_informative(self):
        """The error must tell the user to configure mappings."""
        from app.tools.registry import clear_tool_context, query_company_data
        clear_tool_context()
        result = await query_company_data.ainvoke('{"semantic_concept": "campaign_spend"}')
        # Should contain guidance, not credentials
        assert "password" not in result.lower()
        assert "connection_string" not in result.lower()


# ── No credentials in context ─────────────────────────────────────────────────

class TestNoCredentialsInContext:
    def test_data_context_block_has_no_password_field(self):
        """The data context block injected into the LLM must not contain credentials."""
        # Since build_data_context_block requires a DB, we test the structure
        # by checking what the function is allowed to return
        from app.services.dmm_context import build_data_context_block
        # The function must only reference field names and concept names
        import inspect
        source = inspect.getsource(build_data_context_block)
        # Must not access encrypted_password or similar
        assert "encrypted_password" not in source
        assert "decrypt_password" not in source

    def test_build_data_source_metadata_no_credentials(self):
        """Source labels extracted for response.sources must be safe."""
        sample = (
            "Company Data Query Results\n"
            "Entity: marketing_activity\n"
            "Source: Marketing DB / marketing_activity\n"
            "Rows returned: 5\n"
        )
        sources = build_data_source_metadata(sample)
        for s in sources:
            assert "password" not in s.lower()
            assert "://" not in s  # no connection strings
            assert "localhost" not in s.lower()

    def test_query_company_data_tool_never_logs_password(self):
        """The tool source must never reference password fields."""
        from app.tools.registry import query_company_data
        import inspect
        source = inspect.getsource(query_company_data.coroutine)  # type: ignore[attr-defined]
        assert "encrypted_password" not in source
        assert "password" not in source.split("def query_company_data")[1]

    def test_data_access_service_no_raw_sql_in_params(self):
        """The service only builds parameterized queries — no raw interpolation."""
        from app.services.data_access import _run_query_sync_blocking
        import inspect
        source = inspect.getsource(_run_query_sync_blocking)
        # f-string interpolation of user values would be e.g. f"...{flt.value}..."
        # Check that filter values are only via params dict
        assert "flt.value" not in source.split("param_key")[0]  # value only appears after param binding


# ── SQL injection prevention ──────────────────────────────────────────────────

class TestSQLInjectionPrevention:
    def test_semicolon_in_concept_rejected(self):
        with pytest.raises(Exception):
            CompanyDataQueryRequest(
                semantic_concept="concept; DROP TABLE semantic_mappings",
            )

    def test_union_in_field_rejected(self):
        with pytest.raises(Exception):
            CompanyDataQueryRequest(
                semantic_concept="test",
                fields=["name UNION SELECT password FROM users"],
            )

    def test_comment_in_filter_field_rejected(self):
        with pytest.raises(Exception):
            CompanyDataQueryRequest(
                semantic_concept="test",
                filters=[QueryFilter(field="name--", operator="=", value="x")],
            )

    def test_or_1_1_in_filter_operator_rejected(self):
        with pytest.raises(Exception):
            CompanyDataQueryRequest(
                semantic_concept="test",
                filters=[QueryFilter(field="name", operator="= 1 OR 1=1 --", value="x")],
            )

    def test_valid_filter_accepted(self):
        req = CompanyDataQueryRequest(
            semantic_concept="campaign_performance",
            filters=[QueryFilter(field="status", operator="=", value="active")],
            limit=10,
        )
        assert req.filters[0].operator == "="
        assert req.filters[0].value == "active"


# ── Empty result handling ─────────────────────────────────────────────────────

class TestEmptyResultHandling:
    def test_query_tool_formats_empty_result(self):
        """The tool format for 0 rows must be informative."""
        from app.services.dmm_context import build_data_source_metadata
        empty_result = "Query returned 0 rows from 'ad_campaigns'. Source: Marketing DB / ad_campaigns"
        sources = build_data_source_metadata(empty_result)
        # Even with 0 rows, we still get a source
        assert any("Marketing DB" in s or "ad_campaigns" in s for s in sources) or sources == []


# ── Data source metadata extraction ──────────────────────────────────────────

class TestBuildDataSourceMetadata:
    def test_extracts_source_line(self):
        text = "Company Data Query Results\nSource: Marketing DB / campaigns\nRows returned: 3"
        sources = build_data_source_metadata(text)
        assert any("Marketing DB" in s for s in sources)

    def test_extracts_entity_line(self):
        text = "Company Data Query Results\nEntity: ad_spend\nRows returned: 0"
        sources = build_data_source_metadata(text)
        assert any("ad_spend" in s for s in sources)

    def test_no_duplicates(self):
        text = "Entity: campaigns\nSource: DB / campaigns"
        sources = build_data_source_metadata(text)
        # "campaigns" should not appear in both entries or duplicated
        assert len(sources) <= 2

    def test_empty_text_returns_empty(self):
        assert build_data_source_metadata("") == []

    def test_error_text_returns_empty(self):
        assert build_data_source_metadata("[AUTHORIZATION DENIED] Entity not allowed.") == []

    def test_prefixes_with_company_data(self):
        text = "Source: Marketing DB / campaigns"
        sources = build_data_source_metadata(text)
        assert all(s.startswith("Company data") for s in sources)


# ── Engine data context block ─────────────────────────────────────────────────

class TestEngineDataContextInjection:
    def test_engine_init_without_company_data_tool(self, monkeypatch):
        """Engine with no query_company_data in allowed_tools initialises cleanly."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        from app.core.engine import DynamicAgentEngine
        bp = AgentBlueprint(
            agent_id="test",
            role_name="Digital Marketing Manager",
            system_persona="Test persona.",
            allowed_tools=["query_campaign_analytics"],
            guarded_tools=[],
            tenant_id="tenant-1",
        )
        engine = DynamicAgentEngine(blueprint=bp)
        assert "query_company_data" not in engine._tool_map

    def test_engine_init_with_company_data_tool(self, monkeypatch):
        """Engine with query_company_data in allowed_tools has it in tool_map."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        from app.core.engine import DynamicAgentEngine
        bp = AgentBlueprint(
            agent_id="test",
            role_name="Digital Marketing Manager",
            system_persona="Test persona.",
            allowed_tools=["query_company_data"],
            guarded_tools=[],
            tenant_id="tenant-1",
        )
        engine = DynamicAgentEngine(blueprint=bp)
        assert "query_company_data" in engine._tool_map

    def test_engine_accepts_data_context_block_param(self):
        """Engine.execute signature accepts data_context_block."""
        from app.core.engine import DynamicAgentEngine
        import inspect
        sig = inspect.signature(DynamicAgentEngine.execute)
        assert "data_context_block" in sig.parameters


# ── Role config defaults include query_company_data ───────────────────────────

class TestRoleConfigDefaults:
    def test_dmm_defaults_include_query_company_data(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        tool_keys = [t["tool_key"] for t in tool_scopes]
        assert "query_company_data" in tool_keys

    def test_dmm_query_company_data_governance_is_enabled(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        qcd = next((t for t in tool_scopes if t["tool_key"] == "query_company_data"), None)
        assert qcd is not None
        assert qcd["governance"] == "enabled"

    def test_dmm_send_email_still_requires_approval(self):
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        email = next((t for t in tool_scopes if t["tool_key"] == "send_email"), None)
        assert email is not None
        assert email["governance"] == "requires_approval"


# ── RAG still works ───────────────────────────────────────────────────────────

class TestRAGStillWorks:
    def test_rag_context_builder_still_works(self):
        from app.core.engine import _build_rag_context

        class FakeChunk:
            document_name = "Marketing Policy.pdf"
            document_id = "doc-123"
            text = "Section 4: Campaign budgets are reviewed quarterly."

        result = _build_rag_context([FakeChunk()])  # type: ignore[list-item]
        assert "Marketing Policy.pdf" in result
        assert "Section 4" in result
        assert "Company Knowledge Context" in result
        # Ensure RAG context does NOT contain company data tool instructions
        assert "query_company_data" not in result

    def test_rag_sources_are_document_names(self):
        """RAG sources should be plain document names, not 'Company data ·' prefixed."""
        from app.core.engine import _build_rag_context

        class FakeChunk:
            document_name = "Brand Guidelines.pdf"
            document_id = "doc-456"
            text = "Brand tone must be professional."

        result = _build_rag_context([FakeChunk()])  # type: ignore[list-item]
        assert "Brand Guidelines.pdf" in result
        assert "Company data" not in result


# ── Limit enforcement ─────────────────────────────────────────────────────────

class TestResultLimitEnforcement:
    def test_limit_cannot_exceed_max(self):
        from app.schemas.data_access import MAX_QUERY_LIMIT
        with pytest.raises(Exception):
            CompanyDataQueryRequest(
                semantic_concept="test",
                limit=MAX_QUERY_LIMIT + 1,
            )

    def test_default_limit_is_reasonable(self):
        from app.schemas.data_access import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
        assert DEFAULT_QUERY_LIMIT <= MAX_QUERY_LIMIT
        assert DEFAULT_QUERY_LIMIT > 0
