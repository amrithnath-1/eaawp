"""
EAAWP send_email Action Tool

Sends an email via the tenant's configured external SMTP integration.

Security invariants
-------------------
- Risk level: HIGH — ALWAYS requires human approval, no exceptions.
- Credentials are never passed as action arguments.
- No arbitrary SMTP commands, shell commands, HTTP requests accepted.
- Recipient addresses, subject, and body are schema-validated.
- The integration is loaded from the DB by tenant_id — never from arguments.
- Credentials are decrypted in-memory only during send, then discarded.
- Audit log records safe metadata only (counts, domains, lengths) — never
  the full body, SMTP password, or authentication tokens.

Execution flow (enforced by existing governance):
    Agent detects need
    → planner creates send_email step
    → action_governance validates permission (HIGH → always approval)
    → ApprovalRequest created
    → plan paused (awaiting_approval)
    → human approves in UI
    → governance re-validates permissions + integration
    → send_email.execute() called
    → SMTPEmailProvider sends via configured integration
    → EmailAuditLog written (safe metadata only)
    → result returned to planner
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.db.email_models import EmailAuditLog, ExternalIntegration
from app.integrations.email_provider import get_email_provider
from app.schemas.email_integration import SendEmailInput

logger = logging.getLogger(__name__)


class SendEmailAction(BaseActionTool):
    """
    Sends an email through the tenant's configured SMTP integration.
    Always requires human approval — risk level HIGH.
    """

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="send_email",
            display_name="Send Email",
            description=(
                "Send an email to one or more recipients via the tenant's configured "
                "SMTP integration. This action always requires explicit human approval "
                "before sending. Draft preparation (no send) does not use this action."
            ),
            risk_level="high",
            requires_approval=True,   # HIGH risk — always approval, no exceptions
            target_integration="smtp",
            allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Validate and normalise email arguments using Pydantic schema."""
        try:
            parsed = SendEmailInput(**arguments)
            return True, "", parsed.model_dump()
        except Exception as exc:
            return False, str(exc), {}

    async def execute(
        self,
        arguments: dict[str, Any],
        tenant_id: str,
        role_key: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Send the email after approval.

        Steps:
        1. Re-validate arguments (prevent tampering between proposal and execution).
        2. Load the tenant's email integration — fails safely if not configured.
        3. Check integration is enabled and tested.
        4. Send via provider.
        5. Write safe audit log.
        6. Return result — never includes credentials.
        """
        # 1. Re-validate
        parsed = SendEmailInput(**arguments)

        # 2. Load integration
        integration_result = await db.execute(
            select(ExternalIntegration).where(
                ExternalIntegration.tenant_id == tenant_id,
                ExternalIntegration.provider_type == "smtp",
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            await self._write_audit(
                db, tenant_id, role_key, None, None,
                parsed, False, None, "No SMTP integration configured for this tenant.",
            )
            return {
                "success": False,
                "message": (
                    "Email send failed: no SMTP integration is configured. "
                    "Ask an administrator to configure the email integration first."
                ),
            }

        # 3. Check enabled and status
        if not integration.is_enabled:
            await self._write_audit(
                db, tenant_id, role_key, integration.id, None,
                parsed, False, None, "Email integration is disabled.",
            )
            return {
                "success": False,
                "message": (
                    "Email send failed: the SMTP integration is currently disabled. "
                    "An administrator must re-enable it."
                ),
            }

        if integration.status not in ("connected", "not_tested"):
            # "failed" status means last test failed — warn but still attempt
            logger.warning(
                "send_email for tenant %s: integration status is '%s', attempting anyway",
                tenant_id, integration.status,
            )

        # 4. Send via provider
        provider = await get_email_provider(tenant_id, db)
        if provider is None:
            await self._write_audit(
                db, tenant_id, role_key, integration.id, None,
                parsed, False, None, "Email provider could not be loaded.",
            )
            return {
                "success": False,
                "message": "Email send failed: provider could not be loaded.",
            }

        send_result = await provider.send(
            recipients=parsed.recipients,
            subject=parsed.subject,
            body=parsed.body,
            reply_to=parsed.reply_to,
        )

        # 5. Write safe audit log
        await self._write_audit(
            db, tenant_id, role_key, integration.id,
            send_result.message_id,
            parsed,
            send_result.success,
            send_result.server_response,
            send_result.error_message,
        )

        # 6. Return result — no credentials
        if send_result.success:
            return {
                "success": True,
                "message": (
                    f"Email sent successfully to {len(parsed.recipients)} recipient(s). "
                    f"Subject: '{parsed.subject[:80]}'"
                    + (f". Provider reference: {send_result.message_id}" if send_result.message_id else ".")
                ),
                "recipient_count": len(parsed.recipients),
                "subject": parsed.subject[:80],
            }
        else:
            return {
                "success": False,
                "message": f"Email send failed: {send_result.error_message or 'Unknown provider error.'}",
            }

    async def _write_audit(
        self,
        db: AsyncSession,
        tenant_id: str,
        role_key: str,
        integration_id: str | None,
        message_id: str | None,
        parsed: SendEmailInput,
        success: bool,
        server_response: str | None,
        error_message: str | None,
        approval_request_id: str | None = None,
    ) -> None:
        """
        Write a safe audit record. Never stores credentials, full body, or
        full recipient addresses — only counts and domains.
        """
        try:
            # Extract domains only — not full addresses
            domains = ",".join(
                sorted({addr.split("@")[1] for addr in parsed.recipients if "@" in addr})
            )[:512]

            audit = EmailAuditLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                role_key=role_key,
                integration_id=integration_id,
                approval_request_id=approval_request_id,
                recipient_count=len(parsed.recipients),
                recipient_domains=domains,
                subject_length=len(parsed.subject),
                body_length=len(parsed.body),
                success=success,
                provider_message_id=message_id,
                error_message=(error_message or "")[:400],
                attempted_at=datetime.now(timezone.utc),
            )
            db.add(audit)
            await db.flush()
        except Exception as exc:
            logger.error("Failed to write email audit log: %s", exc)
