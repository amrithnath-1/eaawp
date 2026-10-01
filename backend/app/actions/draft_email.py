"""
EAAWP draft_email Action Tool

Creates a structured email draft with NO external side effects.
The draft is persisted internally so it can be reviewed and then passed
to the send_email action for actual sending after human approval.

Security invariants
-------------------
- Risk level: LOW — no external communication, no SMTP access.
- Never accesses SMTP credentials.
- Never sends email.
- All field validation uses the existing SendEmailInput rules.
- The draft record stores only safe structured data.
- Tenant isolation enforced on all DB operations.

Distinction from send_email
----------------------------
draft_email  → creates internal draft record → NO external side effect
send_email   → sends via SMTP → HIGH risk → ALWAYS requires approval

Workflow
--------
1. Agent analyzes company data / monitoring finding.
2. Agent calls draft_email with recipients, subject, body, purpose.
3. draft_email validates fields and stores a DraftEmail record.
4. The planner surfaces the draft for review.
5. Human reviews the draft and approves.
6. Agent calls send_email with the same fields.
7. Existing governance pauses for human approval.
8. After approval, SMTP sends the email.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.db.email_draft_models import EmailDraft
from app.schemas.email_integration import SendEmailInput


class DraftEmailAction(BaseActionTool):
    """
    Creates a structured email draft record.
    Has NO external side effect — does not send email or access SMTP.
    LOW risk — can execute automatically (no approval required for drafting).
    """

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="draft_email",
            display_name="Draft Email",
            description=(
                "Create a structured email draft for review. "
                "This action has NO external side effect — it does NOT send any email. "
                "Use this to prepare and review an email before submitting it for approval "
                "and sending via send_email."
            ),
            risk_level="low",
            requires_approval=False,   # drafting is safe — no external side effect
            target_integration="internal",
            allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Validate using the same email validation rules as send_email."""
        try:
            parsed = SendEmailInput(**{
                "recipients": arguments.get("recipients", []),
                "subject": arguments.get("subject", ""),
                "body": arguments.get("body", ""),
                "reply_to": arguments.get("reply_to"),
            })
            normalised = parsed.model_dump()
            normalised["purpose"] = str(arguments.get("purpose", ""))[:500]
            normalised["evidence_sources"] = [
                str(s)[:200] for s in arguments.get("evidence_sources", [])
            ][:10]
            return True, "", normalised
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
        Persist a draft email record. Returns safe draft metadata.
        Never accesses SMTP. Never sends email.
        """
        parsed = SendEmailInput(**{
            "recipients": arguments.get("recipients", []),
            "subject": arguments.get("subject", ""),
            "body": arguments.get("body", ""),
            "reply_to": arguments.get("reply_to"),
        })
        purpose = str(arguments.get("purpose", ""))[:500]
        evidence_sources = [str(s)[:200] for s in arguments.get("evidence_sources", [])[:10]]

        draft_id = str(uuid.uuid4())
        import json

        draft = EmailDraft(
            id=draft_id,
            tenant_id=tenant_id,
            role_key=role_key,
            recipients_json=json.dumps(parsed.recipients),
            subject=parsed.subject,
            body=parsed.body,
            reply_to=parsed.reply_to,
            purpose=purpose,
            evidence_sources_json=json.dumps(evidence_sources),
            status="draft",
            created_at=datetime.now(timezone.utc),
        )
        db.add(draft)
        await db.flush()

        recipients_preview = ", ".join(parsed.recipients[:3])
        if len(parsed.recipients) > 3:
            recipients_preview += f" (+{len(parsed.recipients) - 3} more)"

        return {
            "success": True,
            "draft_id": draft_id,
            "message": (
                f"Email draft created successfully.\n"
                f"To: {recipients_preview}\n"
                f"Subject: {parsed.subject[:80]}\n"
                f"Body preview: {parsed.body[:120]}{'...' if len(parsed.body) > 120 else ''}\n"
                f"Purpose: {purpose}\n"
                f"Status: DRAFT — no email has been sent.\n"
                f"To send this email, use the send_email action with the same fields "
                f"after reviewing and approving."
            ),
            "draft_preview": {
                "draft_id": draft_id,
                "recipients": parsed.recipients,
                "subject": parsed.subject,
                "body_preview": parsed.body[:200],
                "purpose": purpose,
                "evidence_sources": evidence_sources,
                "status": "draft",
            },
        }
