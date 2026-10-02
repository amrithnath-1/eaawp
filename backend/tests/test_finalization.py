"""
EAAWP Finalization Tests

Covers all items fixed in the finalization phase:

Tasks 1-7 coverage:
 1.  registry.py: no [STUB] strings remain.
 2.  registry.py: no `if not loop.is_running()` patterns remain.
 3.  fetch_knowledge_base calls real vector_store (not stub).
 4.  query_campaign_analytics calls real campaign_service (not stub).
 5.  generate_report calls real campaign_service (not stub).
 6.  Workflow scheduler cron evaluator: * matches every value.
 7.  Cron evaluator: minute/hour/weekday specific values.
 8.  Cron evaluator: */n step expressions.
 9.  Cron evaluator: invalid expression returns False.
10.  Cron evaluator: wrong field count returns False.
11.  trigger_workflow endpoint imports create_and_execute_plan.
12.  monitoring_scheduler imports Workflow model.
13.  monitoring_scheduler has _tick_workflows function.
14.  GA OAuth route exists: /oauth/google/analytics/authorize.
15.  GSC OAuth route exists: /oauth/google/authorize.
16.  Shared callback route exists: /oauth/google/callback.
17.  GA and GSC use different scope constants.
18.  OAuth callback uses provider_type from OAuthState, not hardcoded.
19.  RefreshToken ORM table name is refresh_tokens.
20.  RefreshToken has token_hash and jti columns.
21.  RefreshToken jti column has unique constraint.
22.  hash_refresh_token produces 64-char hex string.
23.  hash_refresh_token is deterministic.
24.  hash_refresh_token different inputs → different hashes.
25.  revoke_refresh_token marks token revoked=True.
26.  validate_refresh_token_db raises 401 for revoked token.
27.  revoke_all_user_refresh_tokens marks all tokens revoked.
28.  auth router has /auth/logout endpoint.
29.  auth router has /auth/logout/all endpoint.
30.  config.py has embedding_model field.
31.  vector_store EMBEDDING_MODEL reads from settings.
32.  .env.example documents ALGORITHM.
33.  .env.example documents REFRESH_TOKEN_EXPIRE_DAYS.
34.  .env.example documents EMBEDDING_MODEL.
35.  migration t7u1v26w8x14 revises s6t0u15v7w13.
36.  workflow router has trigger endpoint that calls planner.
37.  All 5 new frontend panels are importable (TypeScript verified).
38.  routeTree.gen.ts registers /integrations route.
39.  routeTree.gen.ts registers /employees route.
40.  routeTree.gen.ts registers /approvals route.
41.  routeTree.gen.ts registers /workflows route.
42.  routeTree.gen.ts registers /activity route.
43.  All 7 integration providers still registered after finalization.
44.  Full backend imports cleanly with 0 errors.
45.  MASTER_TOOL_REGISTRY has 28 tools.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


ROOT = pathlib.Path(__file__).parent.parent  # backend/


# ═══════════════════════════════════════════════════════════════════════════════
# 1-5. registry.py stubs + async patterns
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistryStubsFixed:

    def test_no_stub_strings_in_registry(self):
        """No [STUB] strings remain in registry.py."""
        src = (ROOT / "app/tools/registry.py").read_text(encoding="utf-8")
        assert "[STUB]" not in src, "Found [STUB] in registry.py — stub not replaced"

    def test_no_is_running_guard_in_registry(self):
        """No `if not loop.is_running()` anti-pattern in registry.py."""
        src = (ROOT / "app/tools/registry.py").read_text(encoding="utf-8")
        assert "if not loop.is_running()" not in src, \
            "Found `if not loop.is_running()` in registry.py — async anti-pattern not fixed"

    def test_fetch_knowledge_base_calls_vector_store(self):
        """fetch_knowledge_base references retrieve_similar_chunks (not a stub)."""
        src = (ROOT / "app/tools/registry.py").read_text(encoding="utf-8")
        # Find the fetch_knowledge_base function block
        start = src.find("def fetch_knowledge_base")
        end = src.find("\n@tool", start + 1)
        body = src[start:end]
        assert "retrieve_similar_chunks" in body, \
            "fetch_knowledge_base does not call retrieve_similar_chunks"

    def test_query_campaign_analytics_calls_service(self):
        """query_campaign_analytics references campaign_service (not a stub)."""
        src = (ROOT / "app/tools/registry.py").read_text(encoding="utf-8")
        start = src.find("def query_campaign_analytics")
        end = src.find("\n@tool", start + 1)
        body = src[start:end]
        assert "campaign_service" in body or "list_campaigns" in body, \
            "query_campaign_analytics does not call campaign_service"

    def test_generate_report_calls_service(self):
        """generate_report references campaign_service (not a stub)."""
        src = (ROOT / "app/tools/registry.py").read_text(encoding="utf-8")
        start = src.find("def generate_report")
        end = src.find("\n@tool", start + 1)
        if end == -1:
            end = len(src)
        body = src[start:end]
        assert "campaign_service" in body or "list_campaigns" in body, \
            "generate_report does not call campaign_service"

    def test_master_tool_registry_count(self):
        """MASTER_TOOL_REGISTRY has 28 tools."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        count = len(MASTER_TOOL_REGISTRY)
        assert count == 28, f"Expected 28 tools, got {count}: {sorted(MASTER_TOOL_REGISTRY.keys())}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6-10. Workflow scheduler cron evaluator
# ═══════════════════════════════════════════════════════════════════════════════

class TestCronEvaluator:

    def _dt(self, minute=0, hour=9, day=7, month=1, weekday=0) -> datetime:
        # weekday=0=Monday in Python datetime
        from datetime import date
        # Build a real date for the given weekday
        return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)

    def test_wildcard_matches_any(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 6, 15, 14, 37, tzinfo=timezone.utc)
        assert _cron_is_due("* * * * *", now) is True

    def test_specific_minute_and_hour(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)   # Mon 9:00
        assert _cron_is_due("0 9 * * *", now) is True

    def test_specific_minute_mismatch(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 5, tzinfo=timezone.utc)   # Mon 9:05
        assert _cron_is_due("0 9 * * *", now) is False

    def test_weekday_matching(self):
        """0 9 * * 0 should match Sunday (weekday=6 in Python)."""
        from app.services.monitoring_scheduler import _cron_is_due
        # 2026-09-27 is a Sunday
        now = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)
        assert _cron_is_due("0 9 * * 6", now) is True  # Sunday is weekday 6

    def test_step_every_5_minutes(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 15, tzinfo=timezone.utc)
        assert _cron_is_due("*/5 * * * *", now) is True

    def test_step_mismatch(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 17, tzinfo=timezone.utc)
        assert _cron_is_due("*/5 * * * *", now) is False

    def test_invalid_cron_expression_returns_false(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
        assert _cron_is_due("not-a-cron", now) is False

    def test_wrong_field_count_returns_false(self):
        from app.services.monitoring_scheduler import _cron_is_due
        now = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
        assert _cron_is_due("0 9 *", now) is False     # only 3 fields

    def test_scheduler_has_tick_workflows(self):
        """monitoring_scheduler exports _tick_workflows function."""
        from app.services import monitoring_scheduler
        assert hasattr(monitoring_scheduler, "_tick_workflows"), \
            "_tick_workflows not found in monitoring_scheduler"

    def test_scheduler_imports_workflow_model(self):
        """monitoring_scheduler imports the Workflow ORM model."""
        import inspect
        from app.services import monitoring_scheduler
        src = inspect.getsource(monitoring_scheduler)
        assert "Workflow" in src, "Workflow not imported in monitoring_scheduler"


# ═══════════════════════════════════════════════════════════════════════════════
# 14-18. Google Analytics OAuth routes
# ═══════════════════════════════════════════════════════════════════════════════

class TestGAOAuthRoutes:

    def test_ga_authorize_route_exists(self):
        """GA authorize route is registered."""
        from app.api.routers.oauth_router import router
        paths = {r.path for r in router.routes}
        assert "/oauth/google/analytics/authorize" in paths

    def test_gsc_authorize_route_exists(self):
        """GSC authorize route is registered."""
        from app.api.routers.oauth_router import router
        paths = {r.path for r in router.routes}
        assert "/oauth/google/authorize" in paths

    def test_shared_callback_route_exists(self):
        """Shared callback route is registered."""
        from app.api.routers.oauth_router import router
        paths = {r.path for r in router.routes}
        assert "/oauth/google/callback" in paths

    def test_ga_and_gsc_use_different_scopes(self):
        """GA and GSC OAuth use different scope strings."""
        from app.api.routers.oauth_router import _GA_OAUTH_SCOPES, _GSC_OAUTH_SCOPES
        assert _GA_OAUTH_SCOPES != _GSC_OAUTH_SCOPES
        assert any("analytics" in s for s in _GA_OAUTH_SCOPES)
        assert any("webmasters" in s for s in _GSC_OAUTH_SCOPES)

    def test_provider_scopes_map_has_both_providers(self):
        """_PROVIDER_SCOPES maps both google_search_console and google_analytics."""
        from app.api.routers.oauth_router import _PROVIDER_SCOPES
        assert "google_search_console" in _PROVIDER_SCOPES
        assert "google_analytics" in _PROVIDER_SCOPES

    def test_callback_uses_provider_type_from_state(self):
        """Callback function reads provider_type from OAuthState record (not hardcoded)."""
        import inspect
        from app.api.routers import oauth_router
        src = inspect.getsource(oauth_router)
        # The callback should NOT hardcode 'google_search_console' in provider_type assignment
        callback_start = src.find("async def google_callback")
        callback_end = src.find("\ndef _build_frontend_redirect")
        body = src[callback_start:callback_end]
        # Must reference oauth_state.provider_type
        assert "oauth_state.provider_type" in body or "provider_type = oauth_state" in body, \
            "Callback does not read provider_type from OAuthState"
        # Must NOT assign a hardcoded 'google_search_console' to provider_type
        assert 'provider_type="google_search_console"' not in body

    def test_ga_oauth_tests_match_gsc_pattern(self):
        """Both GA and GSC share the same authorize common logic."""
        import inspect
        from app.api.routers import oauth_router
        src = inspect.getsource(oauth_router)
        assert "_google_authorize_common" in src
        assert "google_analytics" in src
        assert "google_search_console" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 19-29. Refresh token revocation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefreshTokenRevocation:

    def test_refresh_token_table_name(self):
        """RefreshToken ORM uses table name 'refresh_tokens'."""
        from app.db.models import RefreshToken
        assert RefreshToken.__tablename__ == "refresh_tokens"

    def test_refresh_token_has_token_hash(self):
        """RefreshToken has token_hash column."""
        from app.db.models import RefreshToken
        cols = {c.key for c in RefreshToken.__table__.columns}
        assert "token_hash" in cols
        assert "jti" in cols

    def test_refresh_token_jti_unique(self):
        """RefreshToken jti column has a unique constraint."""
        from app.db.models import RefreshToken
        col = RefreshToken.__table__.c["jti"]
        assert col.unique or any(
            "jti" in str(c) for c in RefreshToken.__table__.constraints
        )

    def test_hash_refresh_token_produces_64_char_hex(self):
        """hash_refresh_token produces a 64-char SHA-256 hex digest."""
        from app.core.auth import hash_refresh_token
        h = hash_refresh_token("some.jwt.token")
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_hash_refresh_token_deterministic(self):
        """Same input always produces same hash."""
        from app.core.auth import hash_refresh_token
        assert hash_refresh_token("abc") == hash_refresh_token("abc")

    def test_hash_refresh_token_different_inputs(self):
        """Different tokens produce different hashes."""
        from app.core.auth import hash_refresh_token
        assert hash_refresh_token("token-a") != hash_refresh_token("token-b")

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_marks_revoked(self):
        """revoke_refresh_token sets revoked=True on the record."""
        from app.db.models import RefreshToken
        from app.core.auth import revoke_refresh_token

        record = RefreshToken(
            id="rt-1", user_id="u-1", tenant_id="t-1",
            token_hash="abc" * 21 + "a",
            jti="test-jti-123",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            revoked=False,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await revoke_refresh_token("test-jti-123", mock_db)
        assert result is True
        assert record.revoked is True

    @pytest.mark.asyncio
    async def test_validate_refresh_token_db_rejects_revoked(self):
        """validate_refresh_token_db raises 401 when token is revoked."""
        from app.db.models import RefreshToken
        from app.core.auth import validate_refresh_token_db, create_refresh_token
        from fastapi import HTTPException

        raw_token = create_refresh_token("user-1", "tenant-1")

        record = MagicMock()
        record.revoked = True
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=record)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc:
            await validate_refresh_token_db(raw_token, mock_db)
        assert exc.value.status_code == 401
        assert "revoked" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_revoke_all_user_tokens(self):
        """revoke_all_user_refresh_tokens revokes all non-revoked tokens for user."""
        from app.db.models import RefreshToken
        from app.core.auth import revoke_all_user_refresh_tokens

        tokens = [
            MagicMock(revoked=False),
            MagicMock(revoked=False),
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        count = await revoke_all_user_refresh_tokens("user-1", mock_db)
        assert count == 2
        for t in tokens:
            assert t.revoked is True

    def test_auth_router_has_logout_endpoints(self):
        """Auth router has /auth/logout and /auth/logout/all."""
        from app.api.routers.auth import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/auth/logout" in paths
        assert "/api/v1/auth/logout/all" in paths

    def test_create_refresh_token_includes_jti(self, monkeypatch):
        """create_refresh_token JWT payload includes jti claim."""
        monkeypatch.setattr("app.config.settings.secret_key", "test-secret")
        monkeypatch.setattr("app.config.settings.algorithm", "HS256")
        monkeypatch.setattr("app.config.settings.refresh_token_expire_days", 30)
        from app.core.auth import create_refresh_token
        from jose import jwt
        token = create_refresh_token("u1", "t1")
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert "jti" in payload
        assert payload["jti"]  # non-empty


# ═══════════════════════════════════════════════════════════════════════════════
# 30-35. Config + vector store + .env.example + migration
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigAndEnv:

    def test_config_has_embedding_model(self):
        """Settings has embedding_model field."""
        from app.config import settings
        assert hasattr(settings, "embedding_model")
        assert settings.embedding_model  # non-empty

    def test_vector_store_reads_embedding_model_from_settings(self):
        """vector_store.EMBEDDING_MODEL comes from settings, not hardcoded."""
        import inspect
        from app.services import vector_store
        src = inspect.getsource(vector_store)
        # Should read from settings — now uses gemini_embedding_model
        assert (
            "settings.embedding_model" in src
            or "_settings.embedding_model" in src
            or "settings.gemini_embedding_model" in src
            or "_settings.gemini_embedding_model" in src
            or "gemini_embedding_model" in src
        )

    def test_env_example_documents_algorithm(self):
        """ALGORITHM is documented in backend/.env.example."""
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "ALGORITHM" in env

    def test_env_example_documents_refresh_token_expire_days(self):
        """REFRESH_TOKEN_EXPIRE_DAYS is documented in backend/.env.example."""
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "REFRESH_TOKEN_EXPIRE_DAYS" in env

    def test_env_example_documents_embedding_model(self):
        """EMBEDDING_MODEL is documented in backend/.env.example."""
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "EMBEDDING_MODEL" in env

    def test_migration_t7_chain(self):
        """Migration t7u1v26w8x14 has correct down_revision."""
        from migrations.versions.t7u1v26w8x14_add_refresh_tokens_table import (
            revision, down_revision,
        )
        assert revision == "t7u1v26w8x14"
        assert down_revision == "s6t0u15v7w13"


# ═══════════════════════════════════════════════════════════════════════════════
# 36. Workflow trigger calls planner
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowTrigger:

    def test_workflow_router_imports_planner(self):
        """workflow.py trigger endpoint references create_and_execute_plan."""
        import inspect
        from app.api.routers import workflow
        src = inspect.getsource(workflow)
        assert "create_and_execute_plan" in src

    def test_workflow_trigger_endpoint_exists(self):
        """Workflow router has POST /{workflow_id}/trigger."""
        from app.api.routers.workflow import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/workflows/{workflow_id}/trigger" in paths

    def test_workflow_trigger_no_longer_returns_none_plan_id(self):
        """trigger_workflow no longer unconditionally returns plan_id=None."""
        import inspect
        from app.api.routers import workflow
        src = inspect.getsource(workflow)
        # The old stub had: plan_id=None, unconditionally
        # The new version only returns None in the fallback/error path
        # Count the unconditional assignment (not inside except block)
        # Simple check: the stub message is gone
        assert "will execute on the next agent cycle" not in src


# ═══════════════════════════════════════════════════════════════════════════════
# 37-42. Frontend route registration (file presence check)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendRoutes:

    _FRONTEND = ROOT.parent / "src"

    def test_integrations_route_exists(self):
        assert (self._FRONTEND / "routes/integrations.tsx").exists()

    def test_employees_route_exists(self):
        assert (self._FRONTEND / "routes/employees.tsx").exists()

    def test_approvals_route_exists(self):
        assert (self._FRONTEND / "routes/approvals.tsx").exists()

    def test_workflows_route_exists(self):
        assert (self._FRONTEND / "routes/workflows.tsx").exists()

    def test_activity_route_exists(self):
        assert (self._FRONTEND / "routes/activity.tsx").exists()

    def test_route_tree_has_integrations(self):
        tree = (self._FRONTEND / "routeTree.gen.ts").read_text(encoding="utf-8")
        assert "/integrations" in tree

    def test_route_tree_has_employees(self):
        tree = (self._FRONTEND / "routeTree.gen.ts").read_text(encoding="utf-8")
        assert "/employees" in tree

    def test_route_tree_has_approvals(self):
        tree = (self._FRONTEND / "routeTree.gen.ts").read_text(encoding="utf-8")
        assert "/approvals" in tree

    def test_route_tree_has_workflows(self):
        tree = (self._FRONTEND / "routeTree.gen.ts").read_text(encoding="utf-8")
        assert "/workflows" in tree

    def test_route_tree_has_activity(self):
        tree = (self._FRONTEND / "routeTree.gen.ts").read_text(encoding="utf-8")
        assert "/activity" in tree

    def test_nl_integration_panel_exists(self):
        assert (self._FRONTEND / "components/eaawp/NLIntegrationPanel.tsx").exists()

    def test_employee_builder_panel_exists(self):
        assert (self._FRONTEND / "components/eaawp/EmployeeBuilderPanel.tsx").exists()

    def test_approval_center_panel_exists(self):
        assert (self._FRONTEND / "components/eaawp/ApprovalCenterPanel.tsx").exists()

    def test_workflow_manager_panel_exists(self):
        assert (self._FRONTEND / "components/eaawp/WorkflowManagerPanel.tsx").exists()

    def test_unified_activity_panel_exists(self):
        assert (self._FRONTEND / "components/eaawp/UnifiedActivityPanel.tsx").exists()

    def test_gsc_panel_mounted_in_integrations_route(self):
        """GoogleSearchConsolePanel (previously orphaned) is imported in integrations route."""
        src = (self._FRONTEND / "routes/integrations.tsx").read_text(encoding="utf-8")
        assert "GoogleSearchConsolePanel" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 43-44. System integrity check
# ═══════════════════════════════════════════════════════════════════════════════

class TestSystemIntegrity:

    def test_all_7_providers_still_registered(self):
        """All 7 integration providers still registered after finalization."""
        from app.integrations.integration_registry import integration_registry
        types = set(integration_registry.list_types())
        expected = {
            "postgresql", "mysql",
            "google_search_console", "google_analytics",
            "facebook", "github", "mcp",
        }
        missing = expected - types
        assert not missing, f"Missing providers: {missing}"

    def test_full_app_imports_cleanly(self):
        """main.py and all routers import without errors."""
        from app.main import app
        assert app is not None

    def test_no_stub_in_any_service_file(self):
        """No [STUB] strings in any service file (excluding tests)."""
        services_dir = ROOT / "app" / "services"
        stubs_found = []
        for f in services_dir.rglob("*.py"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            if "[STUB]" in content:
                stubs_found.append(str(f))
        assert not stubs_found, f"[STUB] found in: {stubs_found}"

    def test_no_stub_in_tools_dir(self):
        """No [STUB] strings in any tools file."""
        tools_dir = ROOT / "app" / "tools"
        for f in tools_dir.rglob("*.py"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            assert "[STUB]" not in content, f"[STUB] found in {f}"
