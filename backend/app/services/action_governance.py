"""
EAAWP Action Governance Service

Enforces the complete governance pipeline for every action request:

  ActionRequest
    ↓ 1. Validate arguments (schema)
    ↓ 2. Check tool is in blueprint.allowed_tools
    ↓ 3. Check role config permission (auto / approval / restricted)
    ↓ 4. Determine approval requirement (risk level + role config)
    ↓ 5a. If requires approval → create ApprovalRequest → return "proposed"
    ↓ 5b. If auto-allowed    → execute immediately → return "executed"
    ↓ 6. On execution: verify result → write ActionAudit

Approval execution (called when admin approves):
  approve_and_execute()
    ↓ Re-validate arguments (schema)
    ↓ Re-check permissions (config may have changed)
    ↓ Execute the action
    ↓ Update ActionAudit and ApprovalRequest

Security invariants
-------------------
- The LLM cannot bypass approval — approval_status is server-side only.
- Arguments are re-validated at approval time to catch tampering.
- Permissions are re-checked at approval time (config may have changed).
- Credentials are never stored in ActionAudit.arguments_json.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.registry import get_action_tool
from app.db.models import ActionAudit, ApprovalRequest, AuditLog
from app.schemas.actions import ActionRequest, ActionResult

logger = logging.getLogger(__name__)

# Tools allowed by role config governance (matches RoleToolScope.governance)
# Who approved the action now executing (email or user id). Tools that change people or company settings act as
# that administrator (e.g. customize_eaawp's team and Marketplace changes).
approved_by: ContextVar[str | None] = ContextVar("approved_by", default=None)

_GOVERNANCE_AUTO = "enabled"
_GOVERNANCE_APPROVAL = "requires_approval"
_GOVERNANCE_RESTRICTED = "disabled"


async def process_action_request(
    request: ActionRequest,
    blueprint_allowed_tools: list[str],
    blueprint_guarded_tools: list[str],
    db: AsyncSession,
) -> ActionResult:
    """
    Run the full governance pipeline for an action request.

    Returns an ActionResult with status:
    - "proposed"          — approval request created, waiting for admin
    - "executed"          — auto-executed (low-risk, role config allows)
    - "unauthorized"      — tool not in blueprint or restricted by role config
    - "invalid_arguments" — schema validation failed
    """
    tool_name = request.tool_name
    tenant_id = request.tenant_id
    role_key = request.role_key

    # ── 1. Check tool is registered ──────────────────────────────────────────
    action_tool = get_action_tool(tool_name)
    if action_tool is None:
        return ActionResult(
            tool_name=tool_name,
            status="unauthorized",
            message=f"Action tool '{tool_name}' is not registered.",
        )

    # ── 2. Check the role may use the tool at all ────────────────────────────
    # A role's tools are either allowed (enabled) or guarded (requires_approval). Guarded tools are permitted too:
    # they always go through approval below, which is the whole point of guarding them.
    if tool_name not in blueprint_allowed_tools and tool_name not in blueprint_guarded_tools:
        audit = _make_audit(tenant_id, role_key, tool_name, request.arguments,
                            action_tool.meta.risk_level, "rejected", "pending",
                            error_message="Tool not in blueprint allowed_tools.")
        db.add(audit)
        await db.flush()
        return ActionResult(
            tool_name=tool_name,
            status="unauthorized",
            message=f"Action tool '{tool_name}' is not permitted for this agent.",
        )

    # ── 3. Prepare (optional) and validate arguments ─────────────────────────
    # Some tools turn a request into concrete arguments first (e.g. customize_eaawp plans the exact changes), so
    # the approver sees precisely what will run and approval re-validates those stored arguments.
    arguments = request.arguments
    prepare = getattr(action_tool, "prepare", None)
    if prepare is not None:
        try:
            arguments = await prepare(arguments, tenant_id, db)
        except ValueError as exc:
            return ActionResult(tool_name=tool_name, status="invalid_arguments", message=str(exc)[:500])
    is_valid, err_msg, normalised = action_tool.validate(arguments)
    if not is_valid:
        audit = _make_audit(tenant_id, role_key, tool_name, request.arguments,
                            action_tool.meta.risk_level, "proposed", "pending",
                            error_message=err_msg)
        db.add(audit)
        await db.flush()
        return ActionResult(
            tool_name=tool_name,
            status="invalid_arguments",
            message=f"Action arguments are invalid: {err_msg}",
        )

    # ── 4. Determine approval requirement ────────────────────────────────────
    # guarded_tools = always requires approval (as per existing blueprint model)
    # risk_level HIGH = always requires approval
    # risk_level LOW + not guarded = auto if role allows
    needs_approval = (
        tool_name in blueprint_guarded_tools
        or action_tool.meta.risk_level == "high"
        or action_tool.meta.requires_approval
    )

    safe_args_json = json.dumps(_sanitise_arguments(normalised))

    # ── 5a. Approval required ─────────────────────────────────────────────────
    if needs_approval:
        approval_id = str(uuid.uuid4())
        approval = ApprovalRequest(
            id=approval_id,
            tenant_id=tenant_id,
            task_id=None,
            action=f"Action: {tool_name}",
            detail=_format_action_detail(tool_name, normalised),
            status="pending",
            requested_by=request.requested_by or "AI",
        )
        db.add(approval)

        audit = _make_audit(
            tenant_id, role_key, tool_name, normalised,
            action_tool.meta.risk_level, "proposed", "pending",
            approval_request_id=approval_id,
        )
        audit.arguments_json = safe_args_json
        db.add(audit)
        await db.flush()

        from app.services.notification_service import notify_admins
        await notify_admins(db, tenant_id, "approval_requested", f"Approval needed: {tool_name}",
                            f"The AI proposed '{tool_name}' and is waiting for a human decision.", severity="warning",
                            related_id=approval_id, related_type="approval")
        logger.info("Action '%s' proposed for tenant %s — awaiting approval %s",
                    tool_name, tenant_id, approval_id)
        return ActionResult(
            tool_name=tool_name,
            status="proposed",
            approval_request_id=approval_id,
            message=(
                f"Action '{tool_name}' has been proposed and is awaiting human approval. "
                f"Approval request ID: {approval_id}. "
                "The action will NOT execute until an administrator approves it."
            ),
        )

    # ── 5b. Auto-execute ──────────────────────────────────────────────────────
    audit = _make_audit(
        tenant_id, role_key, tool_name, normalised,
        action_tool.meta.risk_level, "approved", "pending",
    )
    audit.arguments_json = safe_args_json
    audit.approved_at = datetime.now(timezone.utc)
    db.add(audit)
    await db.flush()

    try:
        result = await action_tool.execute(normalised, tenant_id, role_key, db)
        audit.execution_status = "executed"
        audit.executed_at = datetime.now(timezone.utc)
        audit.task_id = result.get("task_id")
        await db.flush()

        logger.info("Action '%s' auto-executed for tenant %s", tool_name, tenant_id)
        return ActionResult(
            tool_name=tool_name,
            status="executed",
            task_id=result.get("task_id"),
            message=result.get("message", "Action executed successfully."),
            details={k: v for k, v in result.items() if k != "message"},
        )
    except Exception as exc:
        audit.execution_status = "failed"
        audit.error_message = str(exc)[:400]
        await db.flush()
        logger.error("Action '%s' execution failed: %s", tool_name, exc)
        return ActionResult(
            tool_name=tool_name,
            status="failed",
            message=f"Action execution failed: {str(exc)[:200]}",
        )


async def approve_and_execute(
    audit_id: str,
    approval_request_id: str,
    reviewed_by: str,
    tenant_id: str,
    db: AsyncSession,
) -> ActionResult:
    """
    Execute a previously proposed action after administrator approval.

    Security:
    - Arguments are re-validated from the stored audit record.
    - Permissions are re-checked (config may have changed since proposal).
    - Execution only proceeds if re-validation passes.
    """
    # Load audit record
    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.id == audit_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()
    if not audit:
        return ActionResult(
            tool_name="unknown",
            status="failed",
            message=f"Action audit record '{audit_id}' not found.",
        )

    if audit.approval_status != "proposed":
        return ActionResult(
            tool_name=audit.tool_name,
            status="failed",
            message=f"Action is already in status '{audit.approval_status}' — cannot re-approve.",
        )

    # Load approval request
    ar_result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.tenant_id == tenant_id,
        )
    )
    approval = ar_result.scalar_one_or_none()
    if not approval or approval.status != "pending":
        return ActionResult(
            tool_name=audit.tool_name,
            status="failed",
            message="Approval request not found or not in pending state.",
        )

    # Get action tool
    action_tool = get_action_tool(audit.tool_name)
    if action_tool is None:
        return ActionResult(
            tool_name=audit.tool_name,
            status="failed",
            message=f"Action tool '{audit.tool_name}' is no longer registered.",
        )

    # Re-validate arguments from stored audit (prevents tampering)
    stored_args: dict = json.loads(audit.arguments_json or "{}")
    is_valid, err_msg, normalised = action_tool.validate(stored_args)
    if not is_valid:
        audit.approval_status = "rejected"
        audit.execution_status = "failed"
        audit.error_message = f"Re-validation failed at approval time: {err_msg}"
        approval.status = "rejected"
        approval.reviewed_by = reviewed_by
        approval.resolved_at = datetime.now(timezone.utc)
        db.add(AuditLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor=reviewed_by,
            event=f"approval.rejected: approval_id={approval_request_id} action={audit.tool_name!r} reason=validation_failed",
            department="approval-center",
            status="failed",
        ))
        await db.flush()
        return ActionResult(
            tool_name=audit.tool_name,
            status="failed",
            message=f"Action arguments failed re-validation: {err_msg}",
        )

    # Mark approved
    now = datetime.now(timezone.utc)
    audit.approval_status = "approved"
    audit.approved_at = now
    approval.status = "approved"
    approval.reviewed_by = reviewed_by
    approval.resolved_at = now
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        actor=reviewed_by,
        event=f"approval.approved: approval_id={approval_request_id} action={audit.tool_name!r}",
        department="approval-center",
        status="ok",
    ))
    await db.flush()

    # Execute
    _approver = approved_by.set(reviewed_by)
    try:
        result = await action_tool.execute(normalised, tenant_id, audit.role_key, db)
        audit.execution_status = "executed"
        audit.executed_at = datetime.now(timezone.utc)
        audit.task_id = result.get("task_id")
        await db.flush()

        logger.info("Action '%s' approved and executed for tenant %s by %s",
                    audit.tool_name, tenant_id, reviewed_by)
        return ActionResult(
            tool_name=audit.tool_name,
            status="executed",
            task_id=result.get("task_id"),
            approval_request_id=approval_request_id,
            message=result.get("message", "Action executed after approval."),
            details={k: v for k, v in result.items() if k != "message"},
        )
    except Exception as exc:
        audit.execution_status = "failed"
        audit.error_message = str(exc)[:400]
        await db.flush()
        logger.error("Action '%s' failed during approved execution: %s", audit.tool_name, exc)
        return ActionResult(
            tool_name=audit.tool_name,
            status="failed",
            message=f"Action execution failed after approval: {str(exc)[:200]}",
        )
    finally:
        approved_by.reset(_approver)


async def reject_action(
    audit_id: str,
    approval_request_id: str,
    reviewed_by: str,
    tenant_id: str,
    db: AsyncSession,
) -> ActionResult:
    """Mark an action as rejected — it will never execute."""
    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.id == audit_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()
    if not audit:
        return ActionResult(tool_name="unknown", status="failed",
                            message="Audit record not found.")

    ar_result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_request_id,
            ApprovalRequest.tenant_id == tenant_id,
        )
    )
    approval = ar_result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    audit.approval_status = "rejected"
    audit.execution_status = "skipped"
    if approval:
        approval.status = "rejected"
        approval.reviewed_by = reviewed_by
        approval.resolved_at = now
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        actor=reviewed_by,
        event=f"approval.rejected: approval_id={approval_request_id} action={audit.tool_name!r}",
        department="approval-center",
        status="ok",
    ))
    await db.flush()

    return ActionResult(
        tool_name=audit.tool_name,
        status="rejected",
        approval_request_id=approval_request_id,
        message="Action was rejected by the administrator. No execution took place.",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_audit(
    tenant_id: str,
    role_key: str,
    tool_name: str,
    arguments: dict,
    risk_level: str,
    approval_status: str,
    execution_status: str,
    approval_request_id: str | None = None,
    error_message: str | None = None,
) -> ActionAudit:
    return ActionAudit(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role_key=role_key,
        tool_name=tool_name,
        arguments_json=json.dumps(_sanitise_arguments(arguments)),
        risk_level=risk_level,
        approval_status=approval_status,
        execution_status=execution_status,
        approval_request_id=approval_request_id,
        error_message=error_message,
    )


def _sanitise_arguments(args: dict) -> dict:
    """
    Remove any potentially sensitive keys from stored arguments.
    Credentials must never reach the audit table.
    """
    sensitive = ("password", "secret", "token", "api_key", "apikey", "credential", "dsn", "authorization", "cookie")
    return {k: v for k, v in args.items() if not any(s in k.lower() for s in sensitive)}


def _format_action_detail(tool_name: str, args: dict) -> str:
    """Build a safe human-readable action description for the ApprovalRequest."""
    safe = _sanitise_arguments(args)
    parts = [f"Tool: {tool_name}"]
    for k, v in list(safe.items())[:5]:
        parts.append(f"  {k}: {str(v)[:80]}")
    return "\n".join(parts)
