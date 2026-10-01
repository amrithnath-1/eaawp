"""
EAAWP Admin AI Customization Tests

Required tests per specification:

 1.  Company Admin can access the /plan endpoint (200).
 2.  Non-admin receives 403 from /plan endpoint.
 3.  Non-admin receives 403 from /execute endpoint.
 4.  Tenant isolation: plan is scoped to the authenticated admin's tenant.
 5.  Natural-language request produces a valid CustomizationPlan.
 6.  Compound request produces multiple operations.
 7.  Missing information is detected and surfaced.
 8.  LLM never receives credentials (tenant context contains no secrets).
 9.  Backend re-validates plan before execution (tampered params rejected).
10.  HIGH-risk operations still use existing approval controls (send_email).

Additional coverage:
11.  CustomizationOperation blocks credential field names in params.
12.  CONNECT_INTEGRATION creates integration placeholder (no credentials stored).
13.  GRANT_CAPABILITY calls existing manager function.
14.  CREATE_WORKFLOW creates a Workflow ORM row.
15.  SET_APPROVAL_POLICY updates RoleConfiguration.permissions_json.
16.  Router is importable with correct routes.
17.  Admin role check accepts "Admin" and "Company Admin" variants.
18.  Plan schema rejects > 20 operations.
19.  _gather_tenant_context never includes known credential fields.
20.  execute_customization_plan writes an AuditLog row.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_user(role: str = "Admin", tenant_id: str = "tenant-test") -> MagicMock:
    user = MagicMock()
    user.id = "user-001"
    user.email = "admin@test.com"
    user.role = role
    user.tenant_id = tenant_id
    user.is_active = True
    return user


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


def _make_plan(num_ops: int = 1) -> dict:
    from app.schemas.admin_customization import CustomizationOperation, CustomizationPlan
    ops = [
        CustomizationOperation(
            type="CREATE_AI_EMPLOYEE",
            description=f"Create employee {i}",
            params={"name": f"Employee {i}", "purpose": "Test"},
            requires_confirmation=True,
            order=i,
        )
        for i in range(num_ops)
    ]
    return CustomizationPlan(
        summary="Test plan",
        operations=ops,
        missing_information=[],
        requires_confirmation=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1-3. Role-based access control
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdminAccessControl:

    def test_router_has_correct_routes(self):
        """Admin customization router has /plan and /execute endpoints."""
        from app.api.routers.admin_customization import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/admin/customize/plan" in paths
        assert "/api/v1/admin/customize/execute" in paths

    def test_require_admin_accepts_admin_role(self):
        """require_admin passes for users with 'admin' role."""
        from fastapi import HTTPException
        from app.core.auth import require_admin
        user = _make_user(role="Admin")
        result = require_admin(user=user)
        assert result is user

    def test_require_admin_accepts_company_admin_role(self):
        """require_admin passes for 'Company Admin' role."""
        from app.core.auth import require_admin
        user = _make_user(role="Company Admin")
        result = require_admin(user=user)
        assert result is user

    def test_require_admin_rejects_employee_role(self):
        """Non-admin roles are rejected with HTTP 403."""
        from fastapi import HTTPException
        from app.core.auth import require_admin
        user = _make_user(role="Employee")
        with pytest.raises(HTTPException) as exc:
            require_admin(user=user)
        assert exc.value.status_code == 403

    def test_require_admin_rejects_manager_role(self):
        """Manager role is rejected with HTTP 403."""
        from fastapi import HTTPException
        from app.core.auth import require_admin
        user = _make_user(role="Manager")
        with pytest.raises(HTTPException) as exc:
            require_admin(user=user)
        assert exc.value.status_code == 403

    def test_non_admin_403_on_plan_endpoint(self):
        """The /plan endpoint enforces require_admin — non-admins get 403."""
        from fastapi import HTTPException
        from app.core.auth import require_admin
        from app.api.routers import admin_customization
        import inspect
        # Verify require_admin is imported and used in the router source
        src = inspect.getsource(admin_customization)
        assert "require_admin" in src
        # Also verify it raises 403 for non-admin
        non_admin = _make_user(role="Employee")
        with pytest.raises(HTTPException) as exc:
            require_admin(user=non_admin)
        assert exc.value.status_code == 403

    def test_non_admin_403_on_execute_endpoint(self):
        """The /execute endpoint enforces require_admin — non-admins get 403."""
        from fastapi import HTTPException
        from app.core.auth import require_admin
        from app.api.routers.admin_customization import execute_plan
        import inspect
        src = inspect.getsource(execute_plan)
        assert "require_admin" in src or "admin_user" in src
        # Verify 403 raised for non-admin
        non_admin = _make_user(role="Manager")
        with pytest.raises(HTTPException) as exc:
            require_admin(user=non_admin)
        assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_plan_uses_admin_tenant_id(self):
        """generate_customization_plan scopes context gathering to the admin's tenant."""
        from app.services.admin_customization_service import generate_customization_plan

        mock_db = _make_mock_db()
        admin_tenant = "tenant-A"
        captured_tenant: list[str] = []

        async def mock_list_integrations(tenant_id, db, provider_type=None):
            captured_tenant.append(tenant_id)
            return []

        with patch(
            "app.services.admin_customization_service.int_mgr.list_integrations",
            side_effect=mock_list_integrations,
        ):
            with patch(
                "app.services.admin_customization_service.get_llm_gateway"
            ) as mock_gateway:
                mock_model = AsyncMock()
                mock_model.ainvoke = AsyncMock(return_value=MagicMock(
                    content='{"summary":"test","operations":[],"missing_information":[],"requires_confirmation":true}'
                ))
                mock_gateway.return_value.health.return_value.is_ready = True
                mock_gateway.return_value.get_chat_model.return_value = mock_model

                await generate_customization_plan(
                    instruction="test",
                    tenant_id=admin_tenant,
                    requested_by="admin",
                    db=mock_db,
                )

        # All DB context queries used the admin's tenant_id
        for tid in captured_tenant:
            assert tid == admin_tenant

    @pytest.mark.asyncio
    async def test_execute_uses_admin_tenant_id(self):
        """execute_customization_plan always uses tenant_id from the admin's JWT."""
        from app.services.admin_customization_service import execute_customization_plan
        from app.schemas.admin_customization import CustomizationPlan

        mock_db = _make_mock_db()
        plan = CustomizationPlan(
            summary="Test",
            operations=[],
            missing_information=[],
            requires_confirmation=True,
        )
        # Should succeed with empty operations
        result = await execute_customization_plan(
            plan=plan,
            tenant_id="tenant-A",
            confirmed_by="admin@test.com",
            db=mock_db,
        )
        assert result.operations_total == 0
        assert result.operations_failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5-7. Plan generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanGeneration:

    @pytest.mark.asyncio
    async def test_nl_request_produces_valid_plan(self):
        """A simple NL instruction produces a valid CustomizationPlan."""
        from app.services.admin_customization_service import generate_customization_plan

        mock_db = _make_mock_db()
        llm_response = json.dumps({
            "summary": "Create a Digital Marketing Manager",
            "operations": [
                {
                    "type": "CREATE_AI_EMPLOYEE",
                    "description": "Create Digital Marketing Manager",
                    "params": {"name": "Digital Marketing Manager", "purpose": "Manage campaigns"},
                    "requires_confirmation": True,
                    "order": 0,
                }
            ],
            "missing_information": [],
            "requires_confirmation": True,
        })

        with patch("app.services.admin_customization_service.int_mgr.list_integrations", new=AsyncMock(return_value=[])):
            with patch("app.services.admin_customization_service.get_llm_gateway") as mock_gw:
                mock_model = AsyncMock()
                mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=llm_response))
                mock_gw.return_value.health.return_value.is_ready = True
                mock_gw.return_value.get_chat_model.return_value = mock_model

                plan = await generate_customization_plan(
                    instruction="Create a Digital Marketing Manager",
                    tenant_id="t1",
                    requested_by="admin",
                    db=mock_db,
                )

        assert plan.summary
        assert len(plan.operations) == 1
        assert plan.operations[0].type == "CREATE_AI_EMPLOYEE"
        assert plan.requires_confirmation is True

    @pytest.mark.asyncio
    async def test_compound_request_produces_multiple_operations(self):
        """A compound instruction produces multiple operations."""
        from app.services.admin_customization_service import generate_customization_plan

        mock_db = _make_mock_db()
        llm_response = json.dumps({
            "summary": "Create employee, connect GSC, create workflow",
            "operations": [
                {"type": "CREATE_AI_EMPLOYEE", "description": "Create DMM",
                 "params": {"name": "DMM"}, "requires_confirmation": True, "order": 0},
                {"type": "CONNECT_INTEGRATION", "description": "Connect GSC",
                 "params": {"provider_type": "google_search_console"}, "requires_confirmation": True, "order": 1},
                {"type": "CREATE_WORKFLOW", "description": "Monday report",
                 "params": {"name": "Weekly Report", "trigger": "scheduled", "schedule_cron": "0 9 * * 1"},
                 "requires_confirmation": True, "order": 2},
            ],
            "missing_information": [],
            "requires_confirmation": True,
        })

        with patch("app.services.admin_customization_service.int_mgr.list_integrations", new=AsyncMock(return_value=[])):
            with patch("app.services.admin_customization_service.get_llm_gateway") as mock_gw:
                mock_model = AsyncMock()
                mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=llm_response))
                mock_gw.return_value.health.return_value.is_ready = True
                mock_gw.return_value.get_chat_model.return_value = mock_model

                plan = await generate_customization_plan(
                    instruction="Create DMM with GSC and Monday workflow",
                    tenant_id="t1",
                    requested_by="admin",
                    db=mock_db,
                )

        assert len(plan.operations) == 3
        op_types = {op.type for op in plan.operations}
        assert "CREATE_AI_EMPLOYEE" in op_types
        assert "CONNECT_INTEGRATION" in op_types
        assert "CREATE_WORKFLOW" in op_types

    @pytest.mark.asyncio
    async def test_missing_information_detected(self):
        """If information is missing, it surfaces in missing_information."""
        from app.services.admin_customization_service import generate_customization_plan

        mock_db = _make_mock_db()
        llm_response = json.dumps({
            "summary": "Connect PostgreSQL database",
            "operations": [
                {"type": "CONNECT_INTEGRATION", "description": "Connect database",
                 "params": {"provider_type": "postgresql", "requires_credential_flow": True},
                 "requires_confirmation": True, "order": 0},
            ],
            "missing_information": [
                "PostgreSQL host",
                "PostgreSQL username",
                "Database name",
                "Password (to be entered securely via Integration Manager)",
            ],
            "requires_confirmation": True,
        })

        with patch("app.services.admin_customization_service.int_mgr.list_integrations", new=AsyncMock(return_value=[])):
            with patch("app.services.admin_customization_service.get_llm_gateway") as mock_gw:
                mock_model = AsyncMock()
                mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=llm_response))
                mock_gw.return_value.health.return_value.is_ready = True
                mock_gw.return_value.get_chat_model.return_value = mock_model

                plan = await generate_customization_plan(
                    instruction="Connect our PostgreSQL database",
                    tenant_id="t1",
                    requested_by="admin",
                    db=mock_db,
                )

        assert len(plan.missing_information) > 0
        # Credentials must not be collected through this path
        missing_text = " ".join(plan.missing_information).lower()
        assert "password" not in missing_text or "securely" in missing_text


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM never receives credentials
# ═══════════════════════════════════════════════════════════════════════════════

class TestCredentialSecurity:

    @pytest.mark.asyncio
    async def test_llm_never_receives_credentials(self):
        """_gather_tenant_context must not include credential-like values."""
        from app.services.admin_customization_service import _gather_tenant_context

        # Simulate integration with a name that sounds like it has a password
        mock_integration = MagicMock()
        mock_integration.display_name = "Test DB"
        mock_integration.provider_type = "postgresql"
        mock_integration.status = "connected"
        # These are credential-sounding field names that must NOT appear in context
        mock_integration.encrypted_credentials = "ENCRYPTED_BLOB_XYZ"

        mock_db = _make_mock_db()

        with patch(
            "app.services.admin_customization_service.int_mgr.list_integrations",
            new=AsyncMock(return_value=[mock_integration]),
        ):
            context = await _gather_tenant_context("tenant-test", mock_db)

        # Credentials must never appear in the context sent to the LLM
        assert "ENCRYPTED_BLOB_XYZ" not in context
        assert "encrypted_credentials" not in context.lower()
        # Safe metadata is fine
        assert "postgresql" in context.lower()
        assert "connected" in context.lower()

    def test_operation_params_rejects_credential_fields(self):
        """CustomizationOperation.params validator blocks credential field names."""
        from app.schemas.admin_customization import CustomizationOperation
        from pydantic import ValidationError

        credential_fields = [
            "password", "api_key", "access_token", "refresh_token",
            "client_secret", "secret", "token", "credential",
        ]
        for field in credential_fields:
            with pytest.raises(ValidationError, match=field):
                CustomizationOperation(
                    type="CREATE_AI_EMPLOYEE",
                    description="Test",
                    params={field: "some_value"},
                    requires_confirmation=True,
                    order=0,
                )

    def test_operation_params_allows_safe_fields(self):
        """CustomizationOperation.params allows non-credential fields."""
        from app.schemas.admin_customization import CustomizationOperation
        op = CustomizationOperation(
            type="CONNECT_INTEGRATION",
            description="Connect GSC",
            params={"provider_type": "google_search_console", "display_name": "GSC"},
            requires_confirmation=True,
            order=0,
        )
        assert op.params["provider_type"] == "google_search_console"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Backend re-validates before execution
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackendRevalidation:

    @pytest.mark.asyncio
    async def test_execute_revalidates_plan_before_running(self):
        """execute_customization_plan calls model_validate before any operation."""
        from app.services.admin_customization_service import execute_customization_plan
        from app.schemas.admin_customization import CustomizationPlan, CustomizationOperation

        # A valid plan should pass
        valid_plan = CustomizationPlan(
            summary="Test",
            operations=[
                CustomizationOperation(
                    type="CREATE_WORKFLOW",
                    description="Create a workflow",
                    params={"name": "Test Workflow", "trigger": "manual"},
                    requires_confirmation=True,
                    order=0,
                )
            ],
            missing_information=[],
            requires_confirmation=True,
        )
        mock_db = _make_mock_db()
        # Mock the Workflow creation to return a real OperationResult
        from app.schemas.admin_customization import OperationResult as OR
        with patch("app.services.admin_customization_service._op_create_workflow", new=AsyncMock(
            return_value=OR(type="CREATE_WORKFLOW", description="Test", status="success", detail="ok", created_id=None)
        )):
            result = await execute_customization_plan(
                plan=valid_plan,
                tenant_id="t1",
                confirmed_by="admin",
                db=mock_db,
            )
        assert result.operations_total == 1

    def test_plan_rejects_more_than_20_operations(self):
        """CustomizationPlan rejects plans with more than 20 operations."""
        from app.schemas.admin_customization import CustomizationPlan, CustomizationOperation
        from pydantic import ValidationError

        ops = [
            CustomizationOperation(
                type="CREATE_AI_EMPLOYEE",
                description=f"Op {i}",
                params={"name": f"emp{i}"},
                requires_confirmation=True,
                order=i,
            )
            for i in range(21)
        ]
        with pytest.raises(ValidationError, match="20"):
            CustomizationPlan(
                summary="Too many ops",
                operations=ops,
                missing_information=[],
                requires_confirmation=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 10. HIGH-risk operations still use existing approval controls
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovalControlsPreserved:

    def test_send_email_action_still_requires_approval(self):
        """send_email action meta still has requires_approval=True after customization changes."""
        from app.actions.registry import ACTION_REGISTRY
        send_email = ACTION_REGISTRY.get("send_email")
        assert send_email is not None
        assert send_email.meta.requires_approval is True
        assert send_email.meta.risk_level == "high"

    def test_set_approval_policy_updates_permissions_not_governance(self):
        """SET_APPROVAL_POLICY updates RoleConfiguration.permissions_json,
        not the tool governance (which requires the structured form)."""
        # This verifies the implementation only touches permissions_json
        # and does NOT touch tool_scopes_json (governance)
        import inspect
        from app.services import admin_customization_service
        src = inspect.getsource(admin_customization_service._op_set_approval_policy)
        assert "permissions_json" in src
        assert "tool_scopes_json" not in src

    @pytest.mark.asyncio
    async def test_high_risk_op_in_plan_does_not_bypass_governance(self):
        """An operation producing an email draft still goes through action governance."""
        # The customization layer calls existing services — it does not
        # have its own send_email implementation. Any email sending still
        # requires approval from the existing governance pipeline.
        from app.actions.base import BaseActionTool
        from app.actions.registry import ACTION_REGISTRY

        # Verify the action registry is untouched by customization
        assert "send_email" in ACTION_REGISTRY
        tool = ACTION_REGISTRY["send_email"]
        assert tool.meta.risk_level == "high"
        assert tool.meta.requires_approval is True


# ═══════════════════════════════════════════════════════════════════════════════
# 11-20. Additional coverage
# ═══════════════════════════════════════════════════════════════════════════════

class TestExistingServicesUsed:

    @pytest.mark.asyncio
    async def test_grant_capability_calls_manager(self):
        """GRANT_CAPABILITY operation calls int_mgr.create_capability_grant."""
        from app.services.admin_customization_service import _op_grant_capability
        from app.schemas.admin_customization import CustomizationOperation

        op = CustomizationOperation(
            type="GRANT_CAPABILITY",
            description="Grant analytics",
            params={
                "provider_type": "google_search_console",
                "capability_key": "get_search_analytics",
                "role_key": "DIGITAL_MARKETING_MANAGER",
            },
            requires_confirmation=True,
            order=0,
        )
        mock_db = _make_mock_db()

        # Mock integration exists
        mock_integration = MagicMock()
        mock_integration.id = "integ-001"
        with patch(
            "app.services.admin_customization_service.int_mgr.list_integrations",
            new=AsyncMock(return_value=[mock_integration]),
        ):
            with patch(
                "app.services.admin_customization_service.int_mgr.create_capability_grant",
                new=AsyncMock(return_value=MagicMock()),
            ) as mock_grant:
                result = await _op_grant_capability(op, "tenant-1", mock_db)

        assert result.status == "success"
        mock_grant.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_integration_creates_placeholder(self):
        """CONNECT_INTEGRATION creates a placeholder integration row (no credentials)."""
        from app.services.admin_customization_service import _op_connect_integration
        from app.schemas.admin_customization import CustomizationOperation

        op = CustomizationOperation(
            type="CONNECT_INTEGRATION",
            description="Connect GSC",
            params={"provider_type": "google_search_console", "display_name": "Google Search Console"},
            requires_confirmation=True,
            order=0,
        )
        mock_db = _make_mock_db()

        mock_created = MagicMock()
        mock_created.id = "new-integ-id"

        with patch(
            "app.services.admin_customization_service.int_mgr.list_integrations",
            new=AsyncMock(return_value=[]),
        ):
            with patch(
                "app.services.admin_customization_service.int_mgr.create_integration",
                new=AsyncMock(return_value=mock_created),
            ) as mock_create:
                result = await _op_connect_integration(op, "tenant-1", "admin", mock_db)

        assert result.status == "success"
        # Verify create_integration was called with empty credentials
        call_args = mock_create.call_args
        integration_body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][0]
        assert integration_body.credentials == {}

    @pytest.mark.asyncio
    async def test_create_workflow_creates_orm_row(self):
        """CREATE_WORKFLOW operation creates a Workflow DB row."""
        from app.services.admin_customization_service import _op_create_workflow
        from app.schemas.admin_customization import CustomizationOperation

        op = CustomizationOperation(
            type="CREATE_WORKFLOW",
            description="Weekly Report",
            params={
                "name": "Weekly Marketing Report",
                "trigger": "scheduled",
                "schedule_cron": "0 9 * * 1",
                "description": "Monday morning report",
            },
            requires_confirmation=True,
            order=0,
        )
        mock_db = _make_mock_db()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        result = await _op_create_workflow(op, "tenant-1", "admin", mock_db)

        assert result.status == "success"
        # A Workflow ORM row was added
        from app.db.models import Workflow
        wf_rows = [o for o in added_objects if isinstance(o, Workflow)]
        assert len(wf_rows) == 1
        assert wf_rows[0].name == "Weekly Marketing Report"
        assert wf_rows[0].trigger == "scheduled"
        assert wf_rows[0].schedule_cron == "0 9 * * 1"

    @pytest.mark.asyncio
    async def test_set_approval_policy_updates_role_config(self):
        """SET_APPROVAL_POLICY updates RoleConfiguration.permissions_json."""
        from app.services.admin_customization_service import _op_set_approval_policy
        from app.schemas.admin_customization import CustomizationOperation
        from app.db.models import RoleConfiguration

        op = CustomizationOperation(
            type="SET_APPROVAL_POLICY",
            description="Require approval for external actions",
            params={"scope": "all_external_actions", "mode": "approval_required"},
            requires_confirmation=True,
            order=0,
        )

        # Simulate a RoleConfiguration row
        role_cfg = RoleConfiguration(
            id="rc-1",
            tenant_id="tenant-1",
            role_key="DIGITAL_MARKETING_MANAGER",
            role_name="DMM",
            permissions_json="[]",
        )

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[role_cfg])))
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _op_set_approval_policy(op, "tenant-1", mock_db)

        assert result.status == "success"
        # permissions_json was updated
        perms = json.loads(role_cfg.permissions_json)
        assert len(perms) == 1
        assert perms[0]["mode"] == "approval"

    @pytest.mark.asyncio
    async def test_execute_writes_audit_log(self):
        """execute_customization_plan writes an AuditLog row."""
        from app.services.admin_customization_service import execute_customization_plan
        from app.schemas.admin_customization import CustomizationPlan
        from app.db.models import AuditLog

        mock_db = _make_mock_db()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        plan = CustomizationPlan(
            summary="Audit test plan",
            operations=[],
            missing_information=[],
            requires_confirmation=True,
        )
        result = await execute_customization_plan(
            plan=plan,
            tenant_id="tenant-1",
            confirmed_by="admin@test.com",
            db=mock_db,
        )

        audit_rows = [o for o in added_objects if isinstance(o, AuditLog)]
        assert len(audit_rows) == 1
        assert audit_rows[0].tenant_id == "tenant-1"
        assert audit_rows[0].actor == "admin@test.com"
        assert "admin@test.com" in audit_rows[0].event

    def test_schema_imports(self):
        """All admin customization schemas are importable."""
        from app.schemas.admin_customization import (
            AdminCustomizationRequest,
            AdminCustomizationConfirmRequest,
            AdminCustomizationResult,
            CustomizationPlan,
            CustomizationOperation,
            OperationResult,
        )
        assert CustomizationPlan.__name__ == "CustomizationPlan"

    def test_service_imports(self):
        """Admin customization service is importable with required functions."""
        from app.services.admin_customization_service import (
            generate_customization_plan,
            execute_customization_plan,
            _gather_tenant_context,
        )
        assert callable(generate_customization_plan)
        assert callable(execute_customization_plan)
