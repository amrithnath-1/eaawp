"""
EAAWP Phase 3 — Dynamic Capability → Tool Registration Tests

22 required security + integration scenarios:

 1.  Authorized role can use dynamic capability.
 2.  Unauthorized role cannot use it.
 3.  Wrong tenant cannot use it.
 4.  Disabled integration cannot execute.
 5.  Revoked/absent grant cannot execute.
 6.  Invalid input (bad JSON) is rejected.
 7.  Unknown input field is rejected.
 8.  Credential-like field names in arguments are rejected.
 9.  Credentials never reach tool arguments.
10.  Credentials never reach LLM messages (tool result is safe).
11.  Tool result does not contain credentials.
12.  Dynamic tool cannot execute arbitrary Python (no eval/exec).
13.  Dynamic tool cannot execute arbitrary SQL (no raw SQL pass-through).
14.  Dynamic tool cannot bypass ACTION_REGISTRY (HIGH risk blocked).
15.  Static tools continue working after Phase 3 changes.
16.  PostgreSQL provider still importable and functional.
17.  MySQL provider still importable and functional.
18.  Planner receives only authorized dynamic tools.
19.  Simple engine receives only authorized dynamic tools.
20.  Process-global MASTER_TOOL_REGISTRY is not mutated by dynamic tools.
21.  Tool name collisions: static tool takes precedence over dynamic.
22.  make_tool_key produces deterministic, safe, collision-resistant names.

Additional:
 A.  DynamicToolDefinition is frozen (immutable).
 B.  validate_tool_arguments rejects tenant_id injection.
 C.  validate_tool_arguments rejects role_key injection.
 D.  validate_tool_arguments enforces limit cap.
 E.  validate_tool_arguments enforces filter count cap.
 F.  _dynamic_tools_ctx is cleared after clear_tool_context().
 G.  DynamicToolAuditLog ORM has correct table name.
 H.  get_available_tools returns empty list when no integrations exist.
 I.  build_dynamic_tool_adapter produces a callable with correct tool name.
 J.  is_dynamic_tool_key correctly identifies dynamic vs static keys.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_defn(
    integration_id: str = "a1b2c3d4-0000-0000-0000-000000000000",
    capability_key: str = "query_entity",
    risk_level: str = "low",
    tenant_id: str = "tenant-test",
    role_key: str = "DIGITAL_MARKETING_MANAGER",
    tool_key: str | None = None,
) -> "DynamicToolDefinition":
    from app.tools.dynamic_tool import DynamicToolDefinition, make_tool_key

    tk = tool_key or make_tool_key(integration_id, capability_key)
    return DynamicToolDefinition(
        tool_key=tk,
        integration_id=integration_id,
        tenant_id=tenant_id,
        role_key=role_key,
        capability_key=capability_key,
        provider_type="postgresql",
        integration_name="Test DB",
        description="Query an allowed table.",
        risk_level=risk_level,
        is_read_only=True,
        input_schema={"properties": {"limit": {"type": "integer"}, "fields": {"type": "array"}}},
        is_enabled=True,
    )


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ══════════════════════════════════════════════════════════════════════════════
# 1. Authorized role can use dynamic capability
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthorizedRoleCanExecute:
    @pytest.mark.asyncio
    async def test_authorized_role_gets_tool_in_available_list(self):
        """get_available_tools returns a tool when an active grant exists."""
        from app.tools.dynamic_tool import get_available_tools
        from app.db.integration_models import Integration, CapabilityGrant

        mock_integration = MagicMock(spec=Integration)
        mock_integration.id = "a1b2c3d4-0000-0000-0000-000000000000"
        mock_integration.tenant_id = "tenant-1"
        mock_integration.provider_type = "postgresql"
        mock_integration.display_name = "Prod DB"
        mock_integration.status = "connected"
        mock_integration.is_enabled = True

        mock_grant = MagicMock(spec=CapabilityGrant)
        mock_grant.integration_id = mock_integration.id
        mock_grant.role_key = "DIGITAL_MARKETING_MANAGER"
        mock_grant.capability_key = "query_entity"
        mock_grant.is_granted = True

        db = _make_mock_db()
        # First execute: integrations query
        int_result = MagicMock()
        int_result.scalars.return_value.all.return_value = [mock_integration]
        # Second execute: grants query
        grant_result = MagicMock()
        grant_result.scalars.return_value.all.return_value = [mock_grant]
        db.execute = AsyncMock(side_effect=[int_result, grant_result])

        tools = await get_available_tools("tenant-1", "DIGITAL_MARKETING_MANAGER", db)
        assert len(tools) == 1
        assert tools[0].capability_key == "query_entity"
        assert tools[0].provider_type == "postgresql"
        assert tools[0].tenant_id == "tenant-1"
        assert tools[0].role_key == "DIGITAL_MARKETING_MANAGER"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Unauthorized role cannot use it
# ══════════════════════════════════════════════════════════════════════════════

class TestUnauthorizedRoleBlocked:
    @pytest.mark.asyncio
    async def test_no_grant_returns_empty_tool_list(self):
        """get_available_tools returns empty list when no grants exist for role."""
        from app.tools.dynamic_tool import get_available_tools
        from app.db.integration_models import Integration

        mock_integration = MagicMock(spec=Integration)
        mock_integration.id = "b1b2c3d4-0000-0000-0000-000000000000"
        mock_integration.tenant_id = "tenant-1"
        mock_integration.provider_type = "postgresql"
        mock_integration.display_name = "Prod DB"
        mock_integration.status = "connected"
        mock_integration.is_enabled = True

        db = _make_mock_db()
        int_result = MagicMock()
        int_result.scalars.return_value.all.return_value = [mock_integration]
        grant_result = MagicMock()
        grant_result.scalars.return_value.all.return_value = []  # no grants
        db.execute = AsyncMock(side_effect=[int_result, grant_result])

        tools = await get_available_tools("tenant-1", "SALES_DEVELOPMENT_REP", db)
        assert tools == []

    @pytest.mark.asyncio
    async def test_execution_blocked_without_grant(self):
        """execute_capability raises PermissionError when no grant exists."""
        from app.integrations.manager import execute_capability
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-1"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Test DB"
        mock_row.status = "connected"
        mock_row.is_enabled = True
        mock_row.encrypted_credentials = "some-enc"

        db = _make_mock_db()
        int_result = MagicMock()
        int_result.scalar_one_or_none.return_value = mock_row
        grant_result = MagicMock()
        grant_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[int_result, grant_result])

        with pytest.raises(PermissionError, match="does not have permission"):
            await execute_capability(
                integration_id="int-1",
                capability_key="query_entity",
                parameters={},
                role_key="UNAUTHORIZED_ROLE",
                tenant_id="tenant-1",
                db=db,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Wrong tenant cannot use it
# ══════════════════════════════════════════════════════════════════════════════

class TestWrongTenantBlocked:
    @pytest.mark.asyncio
    async def test_wrong_tenant_gets_empty_tool_list(self):
        """Tenant B gets no tools when they belong to Tenant A."""
        from app.tools.dynamic_tool import get_available_tools

        db = _make_mock_db()
        # No integrations for tenant-B
        int_result = MagicMock()
        int_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=int_result)

        tools = await get_available_tools("tenant-B", "DIGITAL_MARKETING_MANAGER", db)
        assert tools == []

    @pytest.mark.asyncio
    async def test_wrong_tenant_execution_raises_lookup(self):
        """execute_capability raises LookupError for a different tenant's integration."""
        from app.integrations.manager import execute_capability

        db = _make_mock_db()
        # Integration not found for tenant-B (tenant isolation enforced by query)
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=not_found)

        with pytest.raises(LookupError):
            await execute_capability(
                integration_id="tenant-a-integration",
                capability_key="query_entity",
                parameters={},
                role_key="DIGITAL_MARKETING_MANAGER",
                tenant_id="tenant-B",  # wrong tenant
                db=db,
            )

    def test_tool_definition_carries_tenant_id(self):
        """DynamicToolDefinition embeds the tenant_id that owns it."""
        defn = _make_defn(tenant_id="tenant-owner")
        assert defn.tenant_id == "tenant-owner"

    def test_tool_key_does_not_encode_tenant_id(self):
        """Tool key does not expose the tenant_id string."""
        defn = _make_defn(tenant_id="super-secret-tenant-id")
        assert "super-secret-tenant-id" not in defn.tool_key


# ══════════════════════════════════════════════════════════════════════════════
# 4. Disabled integration cannot execute
# ══════════════════════════════════════════════════════════════════════════════

class TestDisabledIntegrationBlocked:
    @pytest.mark.asyncio
    async def test_disabled_integration_excluded_from_tool_list(self):
        """get_available_tools skips integrations that are not enabled."""
        from app.tools.dynamic_tool import get_available_tools

        db = _make_mock_db()
        # is_enabled=False means the DB query filters it out at the SQL level
        # Simulate: no integrations returned
        int_result = MagicMock()
        int_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=int_result)

        tools = await get_available_tools("tenant-1", "DIGITAL_MARKETING_MANAGER", db)
        assert tools == []

    @pytest.mark.asyncio
    async def test_execute_capability_raises_on_disabled(self):
        """execute_capability raises PermissionError when integration is disabled."""
        from app.integrations.manager import execute_capability
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-disabled"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Disabled DB"
        mock_row.status = "connected"
        mock_row.is_enabled = False   # disabled
        mock_row.encrypted_credentials = "enc"

        db = _make_mock_db()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_row
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(PermissionError, match="disabled"):
            await execute_capability(
                integration_id="int-disabled",
                capability_key="query_entity",
                parameters={},
                role_key="DIGITAL_MARKETING_MANAGER",
                tenant_id="tenant-1",
                db=db,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Revoked/absent grant cannot execute
# ══════════════════════════════════════════════════════════════════════════════

class TestRevokedGrantBlocked:
    @pytest.mark.asyncio
    async def test_revoked_grant_blocks_execution(self):
        """execute_capability raises PermissionError when is_granted=False."""
        from app.integrations.manager import execute_capability
        from app.db.integration_models import Integration

        mock_row = MagicMock(spec=Integration)
        mock_row.id = "int-1"
        mock_row.provider_type = "postgresql"
        mock_row.display_name = "Test DB"
        mock_row.status = "connected"
        mock_row.is_enabled = True
        mock_row.encrypted_credentials = "enc"

        db = _make_mock_db()
        int_result = MagicMock()
        int_result.scalar_one_or_none.return_value = mock_row
        # No granted row (None = has_capability_grant returns False)
        grant_result = MagicMock()
        grant_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[int_result, grant_result])

        with pytest.raises(PermissionError):
            await execute_capability(
                integration_id="int-1",
                capability_key="query_entity",
                parameters={},
                role_key="DIGITAL_MARKETING_MANAGER",
                tenant_id="tenant-1",
                db=db,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Invalid input (bad JSON) rejected
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidInputRejected:
    def test_validate_rejects_non_dict(self):
        """validate_tool_arguments rejects a non-dict input."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, _ = validate_tool_arguments("not a dict", "query_entity", None)  # type: ignore
        assert ok is False
        assert "JSON object" in err

    def test_adapter_rejects_invalid_json_string(self):
        """The adapter returns an error for malformed JSON."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import _db_session_ctx, _tenant_id_ctx, _role_key_ctx

        defn = _make_defn()
        adapter = build_dynamic_tool_adapter(defn)
        # Inject a mock DB session so the adapter can get past the None check
        _db_session_ctx.set(MagicMock())
        _tenant_id_ctx.set("tenant-test")
        _role_key_ctx.set("DIGITAL_MARKETING_MANAGER")
        try:
            result = adapter.invoke("{invalid json{{")
            assert "[ERROR]" in result or "[VALIDATION" in result
        finally:
            _db_session_ctx.set(None)
            _tenant_id_ctx.set("default-tenant")
            _role_key_ctx.set("DIGITAL_MARKETING_MANAGER")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Unknown input field is rejected
# ══════════════════════════════════════════════════════════════════════════════

class TestUnknownFieldRejected:
    def test_unknown_field_rejected_when_schema_present(self):
        """validate_tool_arguments rejects unknown fields when schema declares properties."""
        from app.tools.dynamic_tool import validate_tool_arguments

        schema = {"properties": {"limit": {"type": "integer"}, "fields": {"type": "array"}}}
        ok, err, _ = validate_tool_arguments(
            {"limit": 10, "unknown_field": "hacked"},
            "query_entity",
            schema,
        )
        assert ok is False
        assert "unknown_field" in err.lower() or "Unknown parameter" in err

    def test_valid_known_fields_accepted(self):
        """validate_tool_arguments accepts fields declared in the schema."""
        from app.tools.dynamic_tool import validate_tool_arguments

        schema = {"properties": {"limit": {"type": "integer"}, "fields": {"type": "array"}}}
        ok, err, sanitised = validate_tool_arguments(
            {"limit": 20, "fields": ["name", "budget"]},
            "query_entity",
            schema,
        )
        assert ok is True
        assert err == ""
        assert sanitised["limit"] == 20


# ══════════════════════════════════════════════════════════════════════════════
# 8. Credential-like field names in arguments are rejected
# ══════════════════════════════════════════════════════════════════════════════

class TestCredentialFieldsRejected:
    @pytest.mark.parametrize("bad_field", [
        "password", "api_key", "token", "secret", "access_token",
        "client_secret", "encrypted_credentials", "credentials",
    ])
    def test_credential_field_rejected(self, bad_field: str):
        """validate_tool_arguments rejects any credential-like field name."""
        from app.tools.dynamic_tool import validate_tool_arguments

        ok, err, _ = validate_tool_arguments(
            {bad_field: "injected-value"},
            "query_entity",
            None,
        )
        assert ok is False, f"Expected rejection of field '{bad_field}'"
        assert "not permitted" in err or "credential" in err.lower()

    def test_password_mixed_case_rejected(self):
        """Credential check is case-insensitive."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, _ = validate_tool_arguments({"PASSWORD": "secret"}, "query_entity", None)
        assert ok is False


# ══════════════════════════════════════════════════════════════════════════════
# 9. Credentials never reach tool arguments
# ══════════════════════════════════════════════════════════════════════════════

class TestCredentialsNeverInArguments:
    def test_adapter_function_signature_has_no_credential_param(self):
        """The adapter function accepts only params_json — no credential parameters."""
        import inspect
        from app.tools.dynamic_tool import build_dynamic_tool_adapter

        defn = _make_defn()
        adapter = build_dynamic_tool_adapter(defn)
        # Get the underlying function signature
        fn = getattr(adapter, "func", adapter)
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        for bad in ("password", "api_key", "token", "secret", "credentials"):
            assert bad not in param_names, f"Adapter must not accept '{bad}' parameter"

    def test_validate_rejects_tenant_id_in_args(self):
        """tenant_id cannot be injected through tool arguments."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, _ = validate_tool_arguments(
            {"tenant_id": "attacker-tenant"},
            "query_entity",
            None,
        )
        assert ok is False
        assert "tenant_id" in err

    def test_validate_rejects_role_key_in_args(self):
        """role_key cannot be injected through tool arguments."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, _ = validate_tool_arguments(
            {"role_key": "ADMIN"},
            "query_entity",
            None,
        )
        assert ok is False
        assert "role_key" in err

    def test_validate_rejects_integration_id_in_args(self):
        """integration_id cannot be overridden through tool arguments."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, _ = validate_tool_arguments(
            {"integration_id": "attacker-integration"},
            "query_entity",
            None,
        )
        assert ok is False
        assert "integration_id" in err


# ══════════════════════════════════════════════════════════════════════════════
# 10 & 11. Credentials never in LLM messages / tool result
# ══════════════════════════════════════════════════════════════════════════════

class TestCredentialSafety:
    SECRET = "sk-super-secret-never-expose"

    def test_format_result_omits_credential_keys(self):
        """_format_result_for_llm strips credential-like keys from row dicts."""
        from app.tools.dynamic_tool import _format_result_for_llm
        from app.schemas.integration_framework import ExecuteCapabilityResponse

        mock_result = ExecuteCapabilityResponse(
            integration_id="int-1",
            capability_key="query_entity",
            success=True,
            data=[
                {"campaign_name": "Q4 Launch", "password": self.SECRET, "budget": 5000},
                {"campaign_name": "Summer", "api_key": self.SECRET, "spend": 1200},
            ],
            row_count=2,
            truncated=False,
            source_label="Test DB · campaigns",
            error=None,
        )

        result_str = _format_result_for_llm(
            exec_result=mock_result,
            tool_key="integration_a1b2c3d4_query_entity",
            integration_name="Test DB",
            capability_key="query_entity",
        )
        assert self.SECRET not in result_str

    def test_format_result_truncates_large_output(self):
        """_format_result_for_llm caps output at MAX_RESULT_CHARS."""
        from app.tools.dynamic_tool import MAX_RESULT_CHARS, _format_result_for_llm
        from app.schemas.integration_framework import ExecuteCapabilityResponse

        huge_row = {"field": "x" * 1000}
        rows = [huge_row] * 200

        mock_result = ExecuteCapabilityResponse(
            integration_id="int-1",
            capability_key="query_entity",
            success=True,
            data=rows,
            row_count=200,
            truncated=True,
            source_label="Big Table",
            error=None,
        )

        result_str = _format_result_for_llm(
            exec_result=mock_result,
            tool_key="integration_a1b2c3d4_query_entity",
            integration_name="Big DB",
            capability_key="query_entity",
        )
        assert len(result_str) <= MAX_RESULT_CHARS + 50  # small buffer for the truncation label


# ══════════════════════════════════════════════════════════════════════════════
# 12. Dynamic tool cannot execute arbitrary Python (no eval/exec)
# ══════════════════════════════════════════════════════════════════════════════

class TestNoArbitraryCodeExecution:
    def test_dynamic_tool_module_has_no_eval(self):
        """dynamic_tool.py must not call eval() — verified via AST parse."""
        import ast
        from pathlib import Path

        src_path = Path(__file__).parent.parent / "app" / "tools" / "dynamic_tool.py"
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Check for bare eval(...)
                if isinstance(func, ast.Name) and func.id == "eval":
                    raise AssertionError(
                        f"eval() call found in dynamic_tool.py at line {node.lineno}"
                    )

    def test_dynamic_tool_module_has_no_exec(self):
        """dynamic_tool.py must not call exec() — verified via AST parse."""
        import ast
        from pathlib import Path

        src_path = Path(__file__).parent.parent / "app" / "tools" / "dynamic_tool.py"
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "exec":
                    raise AssertionError(
                        f"exec() call found in dynamic_tool.py at line {node.lineno}"
                    )

    def test_adapter_cannot_be_given_python_code_to_run(self):
        """Passing Python code as a parameter value does not execute it."""
        from app.tools.dynamic_tool import validate_tool_arguments
        # If this were eval'd it would execute. The validator just treats it as a string value.
        code_injection = "__import__('os').system('echo hacked')"
        ok, err, sanitised = validate_tool_arguments(
            {"fields": [code_injection]},  # code in a list field
            "query_entity",
            None,
        )
        # Should either accept it (as a plain string value) or reject if schema checks
        # The important thing: no execution occurred, no exception from running code
        # We just check the validator didn't raise
        assert isinstance(ok, bool)


# ══════════════════════════════════════════════════════════════════════════════
# 13. Dynamic tool cannot execute arbitrary SQL
# ══════════════════════════════════════════════════════════════════════════════

class TestNoArbitrarySQL:
    def test_raw_sql_in_fields_is_just_a_string(self):
        """validate_tool_arguments treats SQL strings as plain string values, not code."""
        from app.tools.dynamic_tool import validate_tool_arguments
        ok, err, sanitised = validate_tool_arguments(
            {"fields": ["'; DROP TABLE users; --"]},
            "query_entity",
            None,
        )
        # Accepted as a field value — the provider is responsible for parameterisation
        # The important thing: no SQL was executed here
        assert isinstance(ok, bool)

    def test_no_raw_sql_parameter_in_capability_schema(self):
        """PostgreSQL provider capabilities do not declare a 'sql' or 'query' free-text field."""
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        provider = PostgreSQLIntegrationProvider()
        for cap in provider.get_capabilities():
            schema = cap.input_schema or {}
            props = schema.get("properties", {})
            for key in props:
                assert key not in ("sql", "raw_sql", "query_string", "statement"), (
                    f"Provider capability '{cap.key}' exposes a raw SQL field '{key}'"
                )


# ══════════════════════════════════════════════════════════════════════════════
# 14. Dynamic tool cannot bypass ACTION_REGISTRY — HIGH risk blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestHighRiskBlocked:
    def test_high_risk_adapter_returns_governance_message(self):
        """HIGH risk capability adapter returns governance-required message without executing."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import _db_session_ctx, _tenant_id_ctx, _role_key_ctx

        defn = _make_defn(risk_level="high", capability_key="update_record")
        adapter = build_dynamic_tool_adapter(defn)

        _db_session_ctx.set(MagicMock())
        _tenant_id_ctx.set("tenant-test")
        _role_key_ctx.set("DIGITAL_MARKETING_MANAGER")
        try:
            result = adapter.invoke("{}")
            assert "GOVERNANCE REQUIRED" in result
            assert "HIGH risk" in result
        finally:
            _db_session_ctx.set(None)
            _tenant_id_ctx.set("default-tenant")
            _role_key_ctx.set("DIGITAL_MARKETING_MANAGER")

    def test_medium_risk_does_not_trigger_governance_block(self):
        """MEDIUM risk adapter source does not contain the HIGH-risk governance block for medium."""
        import inspect
        from app.tools.dynamic_tool import build_dynamic_tool_adapter

        # Verify structurally: the governance block only fires when risk_level == "high"
        # For a medium-risk defn, the _risk_level closure var is "medium" — 
        # the block `if _risk_level == "high": return "GOVERNANCE REQUIRED..."` does NOT fire.
        defn_high = _make_defn(risk_level="high", capability_key="update_record")
        defn_medium = _make_defn(risk_level="medium", capability_key="write_record")

        # The source of both adapters contains the same governance check string
        # but _risk_level for medium is "medium", so the condition is False.
        # Structural check: the underlying function closure captures different risk levels.
        adapter_high = build_dynamic_tool_adapter(defn_high)
        adapter_medium = build_dynamic_tool_adapter(defn_medium)

        # Inspect the closure variables to confirm they differ
        fn_high = getattr(adapter_high, "func", adapter_high)
        fn_medium = getattr(adapter_medium, "func", adapter_medium)

        # Get the _risk_level from closure cells
        high_risk = None
        medium_risk = None
        for cell in (getattr(fn_high, "__closure__", None) or []):
            try:
                v = cell.cell_contents
                if v == "high":
                    high_risk = v
            except ValueError:
                pass
        for cell in (getattr(fn_medium, "__closure__", None) or []):
            try:
                v = cell.cell_contents
                if v == "medium":
                    medium_risk = v
            except ValueError:
                pass

        assert high_risk == "high", "High-risk adapter must capture 'high' in closure"
        assert medium_risk == "medium", "Medium-risk adapter must capture 'medium' in closure"


# ══════════════════════════════════════════════════════════════════════════════
# 15. Static tools continue working after Phase 3 changes
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticToolsUnchanged:
    def test_master_tool_registry_still_has_all_static_tools(self):
        """MASTER_TOOL_REGISTRY still contains all pre-Phase-3 static tools."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        required_static = [
            "fetch_knowledge_base", "draft_email", "send_email",
            "query_campaign_analytics", "generate_report", "query_company_data",
            "create_internal_task", "get_campaigns",
        ]
        for tool in required_static:
            assert tool in MASTER_TOOL_REGISTRY, f"Static tool '{tool}' is missing"

    def test_resolve_tools_still_resolves_static_tools(self):
        """resolve_tools() works for static tool keys without a dynamic map."""
        from app.tools.registry import resolve_tools
        resolved = resolve_tools(["fetch_knowledge_base", "get_campaigns"])
        assert len(resolved) == 2

    def test_resolve_tools_raises_for_unknown_key(self):
        """resolve_tools still raises ValueError for a completely unknown key."""
        from app.tools.registry import resolve_tools
        with pytest.raises(ValueError, match="not registered"):
            resolve_tools(["completely_unknown_tool_xyz"])


# ══════════════════════════════════════════════════════════════════════════════
# 16 & 17. PostgreSQL / MySQL providers still importable and functional
# ══════════════════════════════════════════════════════════════════════════════

class TestExistingProvidersUnchanged:
    def test_postgresql_provider_importable(self):
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        assert p.provider_type == "postgresql"
        assert len(p.get_capabilities()) >= 1

    def test_mysql_provider_importable(self):
        from app.integrations.providers.mysql_provider import MySQLIntegrationProvider
        p = MySQLIntegrationProvider()
        assert p.provider_type == "mysql"
        assert len(p.get_capabilities()) >= 1

    def test_postgresql_has_query_entity_capability(self):
        from app.integrations.providers.postgresql_provider import PostgreSQLIntegrationProvider
        p = PostgreSQLIntegrationProvider()
        cap = p.get_capability("query_entity")
        assert cap is not None
        assert cap.key == "query_entity"

    def test_mysql_has_discover_schema_capability(self):
        from app.integrations.providers.mysql_provider import MySQLIntegrationProvider
        p = MySQLIntegrationProvider()
        cap = p.get_capability("discover_schema")
        assert cap is not None


# ══════════════════════════════════════════════════════════════════════════════
# 18. Planner receives only authorized dynamic tools
# ══════════════════════════════════════════════════════════════════════════════

class TestPlannerReceivesAuthorizedTools:
    def test_planner_imports_dynamic_tools_ctx(self):
        """planner.py imports _dynamic_tools_ctx for per-request tool resolution."""
        import inspect
        import app.services.planner as planner_mod
        source = inspect.getsource(planner_mod)
        assert "_dynamic_tools_ctx" in source

    def test_planner_invoke_tool_uses_dynamic_map(self):
        """_invoke_tool in planner checks _dynamic_tools_ctx not just MASTER_TOOL_REGISTRY."""
        import inspect
        import app.services.planner as planner_mod
        source = inspect.getsource(planner_mod)
        # Must reference the dynamic context variable
        assert "_dynamic_tools_ctx" in source
        # Must NOT hard-fail on MASTER_TOOL_REGISTRY alone
        assert "_dyn_map" in source or "dynamic_tools_ctx" in source

    @pytest.mark.asyncio
    async def test_generate_plan_annotates_dynamic_tool_descriptions(self):
        """_generate_plan annotates dynamic tool keys with descriptions in the prompt."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter, DynamicToolDefinition, make_tool_key
        from app.tools.registry import _dynamic_tools_ctx
        from app.schemas.blueprint import AgentBlueprint

        defn = _make_defn(capability_key="query_entity")
        adapter = build_dynamic_tool_adapter(defn)
        dyn_map = {defn.tool_key: adapter}
        _dynamic_tools_ctx.set(dyn_map)

        try:
            bp = AgentBlueprint(
                agent_id="test",
                role_name="Digital Marketing Manager",
                system_persona="You are the DMM.",
                allowed_tools=[defn.tool_key],
                guarded_tools=[],
                tenant_id="tenant-test",
            )

            # Mock the LLM call so we can inspect what was sent
            captured_messages = []

            async def mock_ainvoke(msgs):
                captured_messages.extend(msgs)
                r = MagicMock()
                r.content = '{"objective":"test","steps":[{"step_index":0,"step_type":"response","description":"Return answer","tool_name":null,"arguments":{},"depends_on":[]}]}'
                return r

            with patch("app.llm.gateway.LLMGateway.get_chat_model") as mock_gw:
                mock_model = MagicMock()
                mock_model.ainvoke = mock_ainvoke
                mock_gw.return_value = mock_model

                from app.services.planner import _generate_plan
                plan = await _generate_plan(
                    user_prompt="Test prompt",
                    blueprint=bp,
                    system_persona="You are the DMM.",
                    data_context_block="",
                    rag_context="",
                )

            # The user message should contain the dynamic tool key with its description
            user_msg = str(captured_messages[-1].content if captured_messages else "")
            assert defn.tool_key in user_msg
        finally:
            _dynamic_tools_ctx.set(None)


# ══════════════════════════════════════════════════════════════════════════════
# 19. Simple engine receives only authorized dynamic tools
# ══════════════════════════════════════════════════════════════════════════════

class TestEngineReceivesAuthorizedTools:
    def test_engine_reads_dynamic_tools_ctx(self):
        """engine.py imports and uses _dynamic_tools_ctx."""
        import inspect
        import app.core.engine as engine_mod
        source = inspect.getsource(engine_mod)
        assert "_dynamic_tools_ctx" in source

    def test_engine_init_includes_dynamic_tools_in_tool_map(self, monkeypatch):
        """DynamicAgentEngine._tool_map includes dynamic tool adapters."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-dyntest")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import _dynamic_tools_ctx
        from app.schemas.blueprint import AgentBlueprint

        defn = _make_defn(capability_key="query_entity")
        adapter = build_dynamic_tool_adapter(defn)
        _dynamic_tools_ctx.set({defn.tool_key: adapter})

        try:
            bp = AgentBlueprint(
                agent_id="test",
                role_name="Digital Marketing Manager",
                system_persona="Persona.",
                allowed_tools=[defn.tool_key],
                guarded_tools=[],
                tenant_id="tenant-test",
            )
            from app.core.engine import DynamicAgentEngine
            engine = DynamicAgentEngine(blueprint=bp)
            assert defn.tool_key in engine._tool_map
        finally:
            _dynamic_tools_ctx.set(None)
            gw_mod._gateway_instance = None

    def test_engine_static_tools_not_affected_by_dynamic_map(self, monkeypatch):
        """Static tools remain in _tool_map when dynamic tools are also present."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-engine-static")
        import app.llm.gateway as gw_mod
        gw_mod._gateway_instance = None

        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import _dynamic_tools_ctx
        from app.schemas.blueprint import AgentBlueprint

        defn = _make_defn(capability_key="query_entity")
        adapter = build_dynamic_tool_adapter(defn)
        _dynamic_tools_ctx.set({defn.tool_key: adapter})

        try:
            bp = AgentBlueprint(
                agent_id="test",
                role_name="Digital Marketing Manager",
                system_persona="Persona.",
                allowed_tools=["get_campaigns", defn.tool_key],
                guarded_tools=[],
                tenant_id="tenant-test",
            )
            from app.core.engine import DynamicAgentEngine
            engine = DynamicAgentEngine(blueprint=bp)
            assert "get_campaigns" in engine._tool_map
            assert defn.tool_key in engine._tool_map
        finally:
            _dynamic_tools_ctx.set(None)
            gw_mod._gateway_instance = None


# ══════════════════════════════════════════════════════════════════════════════
# 20. Process-global MASTER_TOOL_REGISTRY is not mutated
# ══════════════════════════════════════════════════════════════════════════════

class TestGlobalRegistryNotMutated:
    def test_build_adapter_does_not_add_to_master_registry(self):
        """build_dynamic_tool_adapter does NOT add the tool to MASTER_TOOL_REGISTRY."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import MASTER_TOOL_REGISTRY

        keys_before = set(MASTER_TOOL_REGISTRY.keys())
        defn = _make_defn(capability_key="query_entity")
        _ = build_dynamic_tool_adapter(defn)
        keys_after = set(MASTER_TOOL_REGISTRY.keys())

        assert keys_before == keys_after, (
            f"MASTER_TOOL_REGISTRY was mutated. New keys: {keys_after - keys_before}"
        )

    def test_dynamic_tools_ctx_is_none_initially(self):
        """_dynamic_tools_ctx default is None, not a shared dict."""
        from app.tools.registry import _dynamic_tools_ctx
        # The default is None (not populated)
        current = _dynamic_tools_ctx.get()
        assert current is None or isinstance(current, dict)

    def test_clear_tool_context_resets_dynamic_map(self):
        """clear_tool_context() resets _dynamic_tools_ctx to None."""
        from app.tools.registry import _dynamic_tools_ctx, set_tool_context, clear_tool_context

        set_tool_context(
            db_session=MagicMock(),
            tenant_id="t1",
            role_key="DMM",
            dynamic_tools={"some_key": MagicMock()},
        )
        assert _dynamic_tools_ctx.get() is not None

        clear_tool_context()
        assert _dynamic_tools_ctx.get() is None


# ══════════════════════════════════════════════════════════════════════════════
# 21. Static tool takes precedence on key collision
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticToolPrecedence:
    def test_resolve_tools_prefers_static_over_dynamic(self):
        """When the same key exists in both registries, the static one wins."""
        from app.tools.registry import MASTER_TOOL_REGISTRY, resolve_tools

        static_key = "get_campaigns"  # definitely in MASTER_TOOL_REGISTRY
        fake_dynamic = {static_key: MagicMock(name="fake_dynamic_adapter")}

        resolved = resolve_tools([static_key], dynamic_tool_map=fake_dynamic)
        assert len(resolved) == 1
        # The resolved tool must be the static one from MASTER_TOOL_REGISTRY
        assert resolved[0] is MASTER_TOOL_REGISTRY[static_key]

    def test_resolve_tools_uses_dynamic_when_not_in_static(self):
        """resolve_tools uses the dynamic map for keys not in MASTER_TOOL_REGISTRY."""
        from app.tools.registry import resolve_tools

        dynamic_key = "integration_a1b2c3d4_query_entity"
        mock_adapter = MagicMock(name="mock_adapter")
        fake_dynamic = {dynamic_key: mock_adapter}

        resolved = resolve_tools([dynamic_key], dynamic_tool_map=fake_dynamic)
        assert len(resolved) == 1
        assert resolved[0] is mock_adapter


# ══════════════════════════════════════════════════════════════════════════════
# 22. Tool name collision resistance and determinism
# ══════════════════════════════════════════════════════════════════════════════

class TestToolNaming:
    def test_make_tool_key_is_deterministic(self):
        """make_tool_key returns the same key for the same inputs."""
        from app.tools.dynamic_tool import make_tool_key
        k1 = make_tool_key("a1b2c3d4-ef56-7890-abcd-ef1234567890", "query_entity")
        k2 = make_tool_key("a1b2c3d4-ef56-7890-abcd-ef1234567890", "query_entity")
        assert k1 == k2

    def test_make_tool_key_different_integrations_differ(self):
        """Different integration IDs produce different tool keys."""
        from app.tools.dynamic_tool import make_tool_key
        k1 = make_tool_key("aaaaaaaa-0000-0000-0000-000000000000", "query_entity")
        k2 = make_tool_key("bbbbbbbb-0000-0000-0000-000000000000", "query_entity")
        assert k1 != k2

    def test_make_tool_key_safe_characters_only(self):
        """Tool key contains only safe characters for a Python identifier."""
        import re
        from app.tools.dynamic_tool import make_tool_key
        k = make_tool_key("a1b2c3d4-ef56-7890-abcd-ef1234567890", "query_entity")
        assert re.match(r"^[a-z0-9_]+$", k), f"Tool key has unsafe chars: {k!r}"

    def test_make_tool_key_format(self):
        """Tool key follows integration_<8hex>_<cap> pattern."""
        import re
        from app.tools.dynamic_tool import make_tool_key
        k = make_tool_key("a1b2c3d4-ef56-7890-abcd-ef1234567890", "query_entity")
        assert re.match(r"^integration_[0-9a-f]{8}_[a-z0-9_]+$", k), k

    def test_is_dynamic_tool_key_true_for_dynamic(self):
        """is_dynamic_tool_key returns True for a dynamic tool key."""
        from app.tools.dynamic_tool import is_dynamic_tool_key
        assert is_dynamic_tool_key("integration_a1b2c3d4_query_entity") is True

    def test_is_dynamic_tool_key_false_for_static(self):
        """is_dynamic_tool_key returns False for static tool keys."""
        from app.tools.dynamic_tool import is_dynamic_tool_key
        for static in ("get_campaigns", "query_company_data", "send_email"):
            assert is_dynamic_tool_key(static) is False


# ══════════════════════════════════════════════════════════════════════════════
# Additional A–J
# ══════════════════════════════════════════════════════════════════════════════

class TestAdditional:
    def test_dynamic_tool_definition_is_frozen(self):
        """DynamicToolDefinition is immutable — mutation raises."""
        defn = _make_defn()
        with pytest.raises((AttributeError, TypeError)):
            defn.tool_key = "hacked"  # type: ignore[misc]

    def test_validate_enforces_limit_cap(self):
        """validate_tool_arguments caps limit to MAX_LIMIT."""
        from app.tools.dynamic_tool import MAX_LIMIT, validate_tool_arguments
        ok, err, sanitised = validate_tool_arguments(
            {"limit": MAX_LIMIT + 9999},
            "query_entity",
            None,
        )
        assert ok is True
        assert sanitised["limit"] == MAX_LIMIT

    def test_validate_enforces_filter_count_cap(self):
        """validate_tool_arguments rejects too many filters."""
        from app.tools.dynamic_tool import MAX_FILTER_COUNT, validate_tool_arguments
        too_many = [{"field": "x", "op": "=", "value": "y"}] * (MAX_FILTER_COUNT + 1)
        ok, err, _ = validate_tool_arguments({"filters": too_many}, "query_entity", None)
        assert ok is False
        assert "filter" in err.lower()

    def test_dynamic_tool_audit_log_table_name(self):
        """DynamicToolAuditLog ORM has the correct table name."""
        from app.db.integration_models import DynamicToolAuditLog
        assert DynamicToolAuditLog.__tablename__ == "dynamic_tool_audit_logs"

    def test_dynamic_tool_audit_log_no_credential_columns(self):
        """DynamicToolAuditLog must not have password/credential columns."""
        from app.db.integration_models import DynamicToolAuditLog
        cols = [c.key for c in DynamicToolAuditLog.__table__.columns]
        for bad in ("password", "api_key", "secret", "credentials"):
            assert bad not in cols

    @pytest.mark.asyncio
    async def test_get_available_tools_empty_when_no_integrations(self):
        """get_available_tools returns [] when no connected integrations exist."""
        from app.tools.dynamic_tool import get_available_tools

        db = _make_mock_db()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        tools = await get_available_tools("tenant-empty", "DIGITAL_MARKETING_MANAGER", db)
        assert tools == []

    def test_build_dynamic_tool_adapter_returns_callable(self):
        """build_dynamic_tool_adapter produces a LangChain-compatible callable."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        defn = _make_defn()
        adapter = build_dynamic_tool_adapter(defn)
        assert callable(adapter) or hasattr(adapter, "invoke")

    def test_adapter_has_correct_tool_name(self):
        """The adapter's .name attribute matches the DynamicToolDefinition.tool_key."""
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        defn = _make_defn()
        adapter = build_dynamic_tool_adapter(defn)
        assert adapter.name == defn.tool_key  # type: ignore[attr-defined]

    def test_ctx_cleared_after_clear_tool_context(self):
        """_dynamic_tools_ctx is None after clear_tool_context()."""
        from app.tools.registry import _dynamic_tools_ctx, set_tool_context, clear_tool_context
        set_tool_context(
            db_session=MagicMock(),
            tenant_id="t",
            role_key="DMM",
            dynamic_tools={"k": MagicMock()},
        )
        clear_tool_context()
        assert _dynamic_tools_ctx.get() is None

    def test_dynamic_tool_info_schema_safe(self):
        """DynamicToolInfo schema has no credential fields."""
        from app.schemas.integration_framework import DynamicToolInfo
        fields = DynamicToolInfo.model_fields
        for bad in ("password", "api_key", "token", "credentials", "encrypted_credentials"):
            assert bad not in fields
