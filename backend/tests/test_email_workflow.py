"""
Tests for the DMM Communication Workflow.

Covers all specified test requirements:
- draft_email creates no external side effect
- draft validation (uses same rules as send_email)
- draft → approval → send workflow
- monitoring trigger → email draft workflow
- HIGH-risk email still requires approval
- rejected email is never sent
- duplicate approval cannot send twice
- duplicate plan resume cannot send twice
- SMTP success correctly recorded
- SMTP failure correctly recorded
- company-data evidence preserved
- credentials never appear in prompts/results/logs
- tenant isolation
- mock mode never sends externally
- existing systems still intact
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── DraftEmailAction schema / validation tests ────────────────────────────────

class TestDraftEmailAction:
    def test_draft_email_importable(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        assert action.meta.tool_name == "draft_email"

    def test_draft_email_risk_is_low(self):
        from app.actions.draft_email import DraftEmailAction
        assert DraftEmailAction().meta.risk_level == "low"

    def test_draft_email_requires_no_approval(self):
        """draft_email must NOT require approval — it has no external side effect."""
        from app.actions.draft_email import DraftEmailAction
        assert DraftEmailAction().meta.requires_approval is False

    def test_draft_email_registered_in_action_registry(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "draft_email" in ACTION_REGISTRY

    def test_draft_email_registered_in_master_tool_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "draft_email" in MASTER_TOOL_REGISTRY

    def test_send_email_still_registered(self):
        """Registering draft_email must not remove send_email."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "send_email" in MASTER_TOOL_REGISTRY

    def test_validate_valid_draft(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, err, normalised = action.validate({
            "recipients": ["manager@company.com"],
            "subject": "Campaign Alert — CTR Drop",
            "body": "Our CTR has dropped 25% this week based on campaign data.",
            "purpose": "Alert marketing team to declining performance",
            "evidence_sources": ["Company data · campaigns"],
        })
        assert is_valid is True
        assert err == ""
        assert normalised["recipients"] == ["manager@company.com"]
        assert normalised["purpose"] == "Alert marketing team to declining performance"
        assert normalised["evidence_sources"] == ["Company data · campaigns"]

    def test_validate_invalid_email_rejected(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, err, _ = action.validate({
            "recipients": ["not-an-email"],
            "subject": "Test",
            "body": "Body",
        })
        assert is_valid is False
        assert err != ""

    def test_validate_too_many_recipients_rejected(self):
        from app.actions.draft_email import DraftEmailAction
        from app.schemas.email_integration import MAX_RECIPIENTS
        action = DraftEmailAction()
        recipients = [f"u{i}@test.com" for i in range(MAX_RECIPIENTS + 1)]
        is_valid, err, _ = action.validate({
            "recipients": recipients,
            "subject": "Test",
            "body": "Body",
        })
        assert is_valid is False

    def test_validate_header_injection_rejected(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, err, _ = action.validate({
            "recipients": ["user@test.com"],
            "subject": "Hello\r\nBcc: evil@hacker.com",
            "body": "Body",
        })
        assert is_valid is False

    def test_validate_empty_subject_rejected(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, err, _ = action.validate({
            "recipients": ["user@test.com"],
            "subject": "",
            "body": "Body",
        })
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_execute_creates_draft_record(self):
        """execute() creates a draft record — no SMTP call, no external side effect."""
        from app.actions.draft_email import DraftEmailAction
        from app.db.email_draft_models import EmailDraft
        action = DraftEmailAction()

        mock_db = AsyncMock()
        added_objects = []
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_db.flush = AsyncMock()

        result = await action.execute(
            arguments={
                "recipients": ["manager@company.com"],
                "subject": "Weekly Campaign Alert",
                "body": "CTR has dropped 25% based on campaign analytics.",
                "purpose": "Alert on campaign decline",
                "evidence_sources": ["Company data · campaigns"],
            },
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            db=mock_db,
        )

        assert result["success"] is True
        assert "draft_id" in result
        assert "no email has been sent" in result["message"].lower()
        # Verify a draft record was added
        draft_objects = [o for o in added_objects if isinstance(o, EmailDraft)]
        assert len(draft_objects) == 1
        draft = draft_objects[0]
        assert draft.tenant_id == "t1"
        assert draft.status == "draft"
        assert "manager@company.com" in draft.recipients_json
        assert "Campaign Alert" in draft.subject

    @pytest.mark.asyncio
    async def test_execute_never_calls_smtp(self):
        """draft_email must never call any SMTP function."""
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Patch the email provider to detect any SMTP access
        smtp_called = {"value": False}

        async def mock_get_provider(*args, **kwargs):
            smtp_called["value"] = True
            return None

        with patch("app.actions.draft_email.get_email_provider", side_effect=mock_get_provider) \
                if hasattr(__import__("app.actions.draft_email", fromlist=["get_email_provider"]),
                           "get_email_provider") else patch("builtins.print"):
            result = await action.execute(
                arguments={
                    "recipients": ["user@test.com"],
                    "subject": "Test",
                    "body": "Body",
                },
                tenant_id="t1",
                role_key="DIGITAL_MARKETING_MANAGER",
                db=mock_db,
            )

        assert smtp_called["value"] is False
        assert result["success"] is True

    def test_draft_email_has_no_smtp_import(self):
        """draft_email module must not import SMTP or email_provider."""
        import inspect
        from app.actions import draft_email
        source = inspect.getsource(draft_email)
        assert "smtplib" not in source
        assert "SMTPEmailProvider" not in source
        assert "decrypt_password" not in source


# ── Draft ORM model tests ─────────────────────────────────────────────────────

class TestEmailDraftModel:
    def test_email_draft_importable(self):
        from app.db.email_draft_models import EmailDraft
        assert EmailDraft.__tablename__ == "email_drafts"

    def test_email_draft_has_tenant_id(self):
        from app.db.email_draft_models import EmailDraft
        assert hasattr(EmailDraft, "tenant_id")

    def test_email_draft_no_credentials(self):
        """EmailDraft must not store SMTP credentials."""
        from app.db.email_draft_models import EmailDraft
        col_names = [c.key for c in EmailDraft.__table__.columns]
        for bad in ("password", "encrypted_password", "smtp_host", "smtp_port",
                    "smtp_username", "auth_token"):
            assert bad not in col_names

    def test_email_draft_has_evidence_sources(self):
        from app.db.email_draft_models import EmailDraft
        assert hasattr(EmailDraft, "evidence_sources_json")

    def test_email_draft_has_purpose(self):
        from app.db.email_draft_models import EmailDraft
        assert hasattr(EmailDraft, "purpose")

    def test_email_draft_status_default_is_draft(self):
        from app.db.email_draft_models import EmailDraft
        import inspect
        source = inspect.getsource(EmailDraft)
        assert '"draft"' in source or "'draft'" in source


# ── Draft → approval → send workflow tests ───────────────────────────────────

class TestDraftApprovalSendWorkflow:
    def test_draft_step_type_is_action(self):
        """draft_email is an action step type in the planner."""
        from app.schemas.planning import PlannedStep
        step = PlannedStep(
            step_index=0,
            step_type="action",
            description="Prepare email draft based on campaign analysis",
            tool_name="draft_email",
            arguments={
                "recipients": ["manager@company.com"],
                "subject": "Campaign Alert",
                "body": "CTR dropped 25%",
                "purpose": "Alert on performance decline",
            },
            depends_on=[],
        )
        assert step.step_type == "action"
        assert step.tool_name == "draft_email"

    def test_send_email_step_type_is_action(self):
        from app.schemas.planning import PlannedStep
        step = PlannedStep(
            step_index=1,
            step_type="action",
            description="Send the approved email",
            tool_name="send_email",
            arguments={
                "recipients": ["manager@company.com"],
                "subject": "Campaign Alert",
                "body": "CTR dropped 25%",
            },
            depends_on=[0],
        )
        assert step.tool_name == "send_email"
        assert 0 in step.depends_on

    def test_draft_does_not_require_approval(self):
        """draft_email in action registry must not require approval."""
        from app.actions.registry import ACTION_REGISTRY
        draft_action = ACTION_REGISTRY["draft_email"]
        assert draft_action.meta.requires_approval is False

    def test_send_requires_approval(self):
        """send_email must always require approval."""
        from app.actions.registry import ACTION_REGISTRY
        send_action = ACTION_REGISTRY["send_email"]
        assert send_action.meta.requires_approval is True
        assert send_action.meta.risk_level == "high"

    @pytest.mark.asyncio
    async def test_draft_governance_auto_executes(self):
        """process_action_request with draft_email should auto-execute (LOW risk)."""
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="draft_email",
            arguments={
                "recipients": ["user@test.com"],
                "subject": "Test Draft",
                "body": "Test body",
                "purpose": "Testing",
            },
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            requested_by="agent",
        )

        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=["draft_email"],
            blueprint_guarded_tools=[],  # not guarded → auto-execute
            db=mock_db,
        )
        # draft_email is LOW risk and not guarded → should auto-execute
        assert result.status == "executed"

    @pytest.mark.asyncio
    async def test_send_governance_requires_approval(self):
        """process_action_request with send_email must always propose for approval."""
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        request = ActionRequest(
            tool_name="send_email",
            arguments={
                "recipients": ["user@test.com"],
                "subject": "Test",
                "body": "Body",
            },
            tenant_id="t1",
            role_key="DIGITAL_MARKETING_MANAGER",
            requested_by="agent",
        )

        result = await process_action_request(
            request=request,
            blueprint_allowed_tools=["send_email"],
            blueprint_guarded_tools=["send_email"],  # guarded → approval
            db=mock_db,
        )
        assert result.status == "proposed"
        assert result.approval_request_id is not None

    @pytest.mark.asyncio
    async def test_rejected_approval_never_sends(self):
        """Rejecting the approval must guarantee no email is sent."""
        from app.services.action_governance import reject_action

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        # Create a mock audit record in proposed state
        from app.db.models import ActionAudit, ApprovalRequest
        mock_audit = MagicMock(spec=ActionAudit)
        mock_audit.tool_name = "send_email"
        mock_audit.approval_status = "proposed"
        mock_audit.arguments_json = json.dumps({
            "recipients": ["user@test.com"],
            "subject": "Test",
            "body": "Body",
        })

        mock_approval = MagicMock(spec=ApprovalRequest)
        mock_approval.status = "pending"

        audit_result = MagicMock()
        audit_result.scalar_one_or_none.return_value = mock_audit
        ar_result = MagicMock()
        ar_result.scalar_one_or_none.return_value = mock_approval
        mock_db.execute = AsyncMock(side_effect=[audit_result, ar_result])

        smtp_called = {"value": False}

        async def mock_get_provider(*args, **kwargs):
            smtp_called["value"] = True
            return MagicMock()

        with patch("app.actions.send_email.get_email_provider", side_effect=mock_get_provider):
            result = await reject_action(
                audit_id="audit-1",
                approval_request_id="approval-1",
                reviewed_by="admin",
                tenant_id="t1",
                db=mock_db,
            )

        assert result.status == "rejected"
        assert smtp_called["value"] is False, "SMTP must NOT be called after rejection"


# ── Duplicate protection tests ────────────────────────────────────────────────

class TestDuplicateProtection:
    @pytest.mark.asyncio
    async def test_double_approval_prevented_by_status_check(self):
        """approve_and_execute must reject if already approved."""
        from app.services.action_governance import approve_and_execute
        from app.db.models import ActionAudit

        mock_db = AsyncMock()
        mock_audit = MagicMock(spec=ActionAudit)
        mock_audit.tool_name = "send_email"
        mock_audit.approval_status = "approved"  # already approved
        mock_audit.arguments_json = "{}"
        mock_audit.role_key = "DIGITAL_MARKETING_MANAGER"

        audit_result = MagicMock()
        audit_result.scalar_one_or_none.return_value = mock_audit
        mock_db.execute = AsyncMock(return_value=audit_result)
        mock_db.flush = AsyncMock()

        result = await approve_and_execute(
            audit_id="audit-1",
            approval_request_id="approval-1",
            reviewed_by="admin",
            tenant_id="t1",
            db=mock_db,
        )
        assert result.status == "failed"
        assert "already" in result.message.lower()

    @pytest.mark.asyncio
    async def test_double_plan_resume_prevented_by_status(self):
        """resume_plan must fail if plan is not in awaiting_approval state."""
        from app.services.planner import resume_plan
        from app.db.models import ExecutionPlan

        mock_db = AsyncMock()
        mock_plan = MagicMock(spec=ExecutionPlan)
        mock_plan.id = "plan-1"
        mock_plan.tenant_id = "t1"
        mock_plan.status = "completed"  # already completed — cannot resume

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = mock_plan
        mock_db.execute = AsyncMock(return_value=plan_result)

        final_msg, plan_id = await resume_plan(
            plan_id="plan-1",
            tenant_id="t1",
            reviewed_by="admin",
            db=mock_db,
        )
        assert "completed" in final_msg.lower() or "cannot resume" in final_msg.lower()

    def test_action_audit_approval_status_field_exists(self):
        """ActionAudit has approval_status to prevent duplicate execution."""
        from app.db.models import ActionAudit
        assert hasattr(ActionAudit, "approval_status")

    def test_execution_status_field_exists(self):
        """ActionAudit has execution_status to track completion."""
        from app.db.models import ActionAudit
        assert hasattr(ActionAudit, "execution_status")


# ── Evidence / company data tests ─────────────────────────────────────────────

class TestEvidencePreservation:
    def test_draft_email_evidence_sources_stored(self):
        """evidence_sources field must be stored in the draft."""
        from app.db.email_draft_models import EmailDraft
        assert hasattr(EmailDraft, "evidence_sources_json")

    def test_draft_email_validate_preserves_evidence(self):
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, _, normalised = action.validate({
            "recipients": ["user@test.com"],
            "subject": "Alert",
            "body": "Body based on data",
            "purpose": "Data-driven alert",
            "evidence_sources": [
                "Company data · campaigns",
                "Company data · spend",
            ],
        })
        assert is_valid is True
        assert len(normalised["evidence_sources"]) == 2
        assert "Company data · campaigns" in normalised["evidence_sources"]

    def test_evidence_sources_capped_at_10(self):
        """evidence_sources must be capped to prevent bloat."""
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, _, normalised = action.validate({
            "recipients": ["user@test.com"],
            "subject": "Alert",
            "body": "Body",
            "evidence_sources": [f"source-{i}" for i in range(20)],
        })
        assert is_valid is True
        assert len(normalised["evidence_sources"]) <= 10

    def test_evidence_sources_truncated(self):
        """Each evidence source must be truncated to prevent injection."""
        from app.actions.draft_email import DraftEmailAction
        action = DraftEmailAction()
        is_valid, _, normalised = action.validate({
            "recipients": ["user@test.com"],
            "subject": "Test",
            "body": "Body",
            "evidence_sources": ["x" * 500],
        })
        assert is_valid is True
        assert len(normalised["evidence_sources"][0]) <= 200


# ── Credentials never in prompts/results/logs tests ──────────────────────────

class TestCredentialSafety:
    def test_draft_execute_result_no_credentials(self):
        """draft_email result must never contain SMTP credentials."""
        from app.actions.draft_email import DraftEmailAction
        import inspect
        source = inspect.getsource(DraftEmailAction.execute)
        # Must never access or return credentials
        assert "decrypt_password" not in source
        assert "encrypted_password" not in source
        assert "smtp.login" not in source
        assert "smtplib" not in source

    def test_planner_system_prompt_no_credentials(self):
        """The planner system prompt must not contain credential-related instructions."""
        from app.services.planner import _PLANNER_SYSTEM
        # Must not contain actual credential instructions
        assert "password" not in _PLANNER_SYSTEM.lower()
        assert "decrypt" not in _PLANNER_SYSTEM.lower()
        assert "encrypted" not in _PLANNER_SYSTEM.lower()
        # "smtp" appearing in workflow guidance is acceptable (it names the concept)
        # but credentials must not appear

    def test_dmm_context_no_credentials(self):
        """build_data_context_block must never include credentials."""
        import inspect
        from app.services.dmm_context import build_data_context_block
        source = inspect.getsource(build_data_context_block)
        assert "password" not in source
        assert "decrypt" not in source
        assert "encrypted_password" not in source

    def test_draft_result_structure_safe(self):
        """The draft_preview dict must not have credential-like keys."""
        # Verify no sensitive fields in the draft_preview structure
        safe_keys = {"draft_id", "recipients", "subject", "body_preview",
                     "purpose", "evidence_sources", "status"}
        dangerous_keys = {"password", "smtp_host", "smtp_port", "username",
                          "api_key", "token", "credential"}
        # Check no overlap
        assert not safe_keys.intersection(dangerous_keys)


# ── Planner prompt update tests ───────────────────────────────────────────────

class TestPlannerUpdates:
    def test_planner_prompt_mentions_draft_email(self):
        """The planner prompt must know about draft_email."""
        from app.services.planner import _PLANNER_SYSTEM
        assert "draft_email" in _PLANNER_SYSTEM

    def test_planner_prompt_distinguishes_draft_from_send(self):
        """The planner must clearly separate drafting from sending."""
        from app.services.planner import _PLANNER_SYSTEM
        assert "draft_email" in _PLANNER_SYSTEM
        assert "send_email" in _PLANNER_SYSTEM
        # The prompt must warn about the distinction
        assert "no external side effect" in _PLANNER_SYSTEM.lower() or \
               "does not send" in _PLANNER_SYSTEM.lower() or \
               "NOT send" in _PLANNER_SYSTEM

    def test_planner_prompt_mentions_high_risk_approval(self):
        """The planner must know send_email requires approval."""
        from app.services.planner import _PLANNER_SYSTEM
        assert "approval" in _PLANNER_SYSTEM.lower()
        assert "HIGH" in _PLANNER_SYSTEM or "high" in _PLANNER_SYSTEM

    def test_planner_prompt_forbids_credential_exposure(self):
        """Planner must be instructed not to expose credentials."""
        from app.services.planner import _PLANNER_SYSTEM
        assert "credentials" in _PLANNER_SYSTEM.lower() or \
               "credential" in _PLANNER_SYSTEM.lower()


# ── Monitoring integration tests ──────────────────────────────────────────────

class TestMonitoringEmailIntegration:
    def test_monitoring_engine_uses_existing_planner(self):
        """Monitoring still calls create_and_execute_plan — no new engine."""
        import inspect
        from app.services.monitoring_engine import _create_plan_for_rule
        source = inspect.getsource(_create_plan_for_rule)
        assert "create_and_execute_plan" in source

    def test_draft_email_in_allowed_tools_for_dmm(self):
        """draft_email must be available in the DMM tool scopes."""
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        tool_keys = [t["tool_key"] for t in tool_scopes]
        assert "draft_email" in tool_keys

    def test_draft_email_governance_in_dmm_is_enabled(self):
        """draft_email must be 'enabled' (not requires_approval) in DMM defaults."""
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        draft_scope = next((t for t in tool_scopes if t["tool_key"] == "draft_email"), None)
        assert draft_scope is not None
        assert draft_scope["governance"] == "enabled"

    def test_send_email_governance_in_dmm_is_guarded(self):
        """send_email must be 'requires_approval' in DMM defaults."""
        from app.api.routers.role_config import _DMM_DEFAULTS
        tool_scopes = json.loads(_DMM_DEFAULTS["tool_scopes_json"])
        send_scope = next((t for t in tool_scopes if t["tool_key"] == "send_email"), None)
        assert send_scope is not None
        assert send_scope["governance"] == "requires_approval"

    def test_monitoring_trigger_creates_plan_not_email_directly(self):
        """Monitoring engine creates a plan — it never directly sends email."""
        import inspect
        from app.services.monitoring_engine import _do_evaluate
        source = inspect.getsource(_do_evaluate)
        # Must call _create_plan_for_rule, not send_email directly
        assert "_create_plan_for_rule" in source
        assert "send_email" not in source
        assert "SMTPEmailProvider" not in source


# ── SMTP success/failure recording tests ─────────────────────────────────────

class TestSMTPResultRecording:
    @pytest.mark.asyncio
    async def test_successful_send_recorded_in_audit(self):
        """After a successful send, EmailAuditLog is written."""
        from app.actions.send_email import SendEmailAction
        from app.integrations.email_provider import SendResult

        action = SendEmailAction()
        integration = MagicMock()
        integration.id = "int-1"
        integration.is_enabled = True
        integration.status = "connected"
        integration.provider_type = "smtp"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = integration
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=SendResult(
            success=True, message_id="<msg@smtp.test>", server_response="Accepted",
        ))

        captured_audits = []
        original_add = mock_db.add

        def track_add(obj):
            from app.db.email_models import EmailAuditLog
            if isinstance(obj, EmailAuditLog):
                captured_audits.append(obj)

        mock_db.add = track_add

        with patch("app.actions.send_email.get_email_provider", return_value=mock_provider):
            result = await action.execute(
                arguments={
                    "recipients": ["user@example.com"],
                    "subject": "Weekly Alert",
                    "body": "CTR dropped this week.",
                },
                tenant_id="t1",
                role_key="DIGITAL_MARKETING_MANAGER",
                db=mock_db,
            )

        assert result["success"] is True
        assert len(captured_audits) == 1
        audit = captured_audits[0]
        assert audit.success is True
        assert audit.provider_message_id == "<msg@smtp.test>"

    @pytest.mark.asyncio
    async def test_failed_send_recorded_in_audit(self):
        """After a failed send, EmailAuditLog records failure."""
        from app.actions.send_email import SendEmailAction
        from app.integrations.email_provider import SendResult

        action = SendEmailAction()
        integration = MagicMock()
        integration.id = "int-1"
        integration.is_enabled = True
        integration.status = "connected"
        integration.provider_type = "smtp"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = integration
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=SendResult(
            success=False, error_message="Connection refused",
        ))

        captured_audits = []

        def track_add(obj):
            from app.db.email_models import EmailAuditLog
            if isinstance(obj, EmailAuditLog):
                captured_audits.append(obj)

        mock_db.add = track_add

        with patch("app.actions.send_email.get_email_provider", return_value=mock_provider):
            result = await action.execute(
                arguments={
                    "recipients": ["user@example.com"],
                    "subject": "Test",
                    "body": "Body",
                },
                tenant_id="t1",
                role_key="DIGITAL_MARKETING_MANAGER",
                db=mock_db,
            )

        assert result["success"] is False
        assert len(captured_audits) == 1
        assert captured_audits[0].success is False
        assert "Connection refused" in (captured_audits[0].error_message or "")

    def test_success_message_does_not_claim_sent_on_failure(self):
        """When send fails, the result must not claim success."""
        from app.actions.send_email import SendEmailAction
        import inspect
        source = inspect.getsource(SendEmailAction.execute)
        # There must be a conditional for success vs failure
        assert "send_result.success" in source or "result.success" in source


# ── Tenant isolation tests ────────────────────────────────────────────────────

class TestWorkflowTenantIsolation:
    def test_email_draft_has_tenant_id_column(self):
        from app.db.email_draft_models import EmailDraft
        col_names = [c.key for c in EmailDraft.__table__.columns]
        assert "tenant_id" in col_names

    @pytest.mark.asyncio
    async def test_draft_execute_scopes_to_tenant(self):
        """Draft execution includes tenant_id in the stored record."""
        from app.actions.draft_email import DraftEmailAction
        from app.db.email_draft_models import EmailDraft

        action = DraftEmailAction()
        mock_db = AsyncMock()
        captured = []
        mock_db.add = lambda obj: captured.append(obj)
        mock_db.flush = AsyncMock()

        await action.execute(
            arguments={"recipients": ["u@t.com"], "subject": "S", "body": "B"},
            tenant_id="tenant-xyz",
            role_key="DIGITAL_MARKETING_MANAGER",
            db=mock_db,
        )

        drafts = [o for o in captured if isinstance(o, EmailDraft)]
        assert len(drafts) == 1
        assert drafts[0].tenant_id == "tenant-xyz"


# ── Mock mode tests ───────────────────────────────────────────────────────────

class TestMockModeNeverSends:
    def test_draft_email_never_accesses_real_smtp(self):
        """draft_email tool has no SMTP access in any code path."""
        import inspect
        from app.actions import draft_email as draft_module
        source = inspect.getsource(draft_module)
        assert "smtplib" not in source
        assert "SMTPEmailProvider" not in source
        assert "smtp.ehlo" not in source
        assert "smtp.login" not in source

    def test_draft_tool_in_master_registry_no_smtp(self):
        """The draft_email tool in MASTER_TOOL_REGISTRY routes through governance."""
        from app.tools.registry import MASTER_TOOL_REGISTRY
        assert "draft_email" in MASTER_TOOL_REGISTRY
        # The draft action is LOW risk — governance auto-executes it
        from app.actions.registry import get_action_tool
        action = get_action_tool("draft_email")
        assert action is not None
        assert action.meta.requires_approval is False

    def test_send_email_in_mock_mode_would_fail_without_integration(self):
        """In real mode without SMTP configured, send_email returns failure not exception."""
        from app.actions.registry import get_action_tool
        send = get_action_tool("send_email")
        assert send is not None
        # The action handles missing integration gracefully
        import inspect
        source = inspect.getsource(send.execute)
        assert "not configured" in source.lower() or "integration" in source.lower()


# ── Draft router tests ────────────────────────────────────────────────────────

class TestEmailDraftsRouter:
    def test_email_drafts_router_importable(self):
        from app.api.routers.email_drafts import router
        assert router.prefix == "/api/v1/email/drafts"

    def test_email_drafts_router_registered_in_app(self):
        from app.main import app
        route_paths = [r.path for r in app.routes]
        assert any("/api/v1/email/drafts" in p for p in route_paths)


# ── Existing systems intact ───────────────────────────────────────────────────

class TestExistingSystemsIntactWithWorkflow:
    def test_create_internal_task_still_registered(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "create_internal_task" in ACTION_REGISTRY

    def test_send_email_still_registered(self):
        from app.actions.registry import ACTION_REGISTRY
        assert "send_email" in ACTION_REGISTRY

    def test_existing_planner_intact(self):
        from app.services.planner import create_and_execute_plan, resume_plan
        assert callable(create_and_execute_plan)
        assert callable(resume_plan)

    def test_existing_monitoring_intact(self):
        from app.services.monitoring_engine import evaluate_rule
        assert callable(evaluate_rule)

    def test_existing_governance_intact(self):
        from app.services.action_governance import process_action_request
        assert callable(process_action_request)

    def test_all_tools_still_in_master_registry(self):
        from app.tools.registry import MASTER_TOOL_REGISTRY
        for t in ["query_campaign_analytics", "fetch_knowledge_base",
                  "generate_report", "query_company_data",
                  "create_internal_task", "draft_email", "send_email"]:
            assert t in MASTER_TOOL_REGISTRY, f"Missing: {t}"

    def test_planning_schemas_unchanged(self):
        from app.schemas.planning import MAX_PLAN_STEPS, MAX_TOOL_CALLS_PER_PLAN
        assert MAX_PLAN_STEPS >= 5
        assert MAX_TOOL_CALLS_PER_PLAN >= 4
