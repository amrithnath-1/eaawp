"""
EAAWP Email Drafts Router

Read-only access to email drafts created by the draft_email action.
Used by the frontend to render structured email previews in the chat.

Endpoints
---------
GET  /api/v1/email/drafts                 — list recent drafts for tenant
GET  /api/v1/email/drafts/{draft_id}      — get a specific draft
POST /api/v1/email/drafts/{draft_id}/cancel — cancel a pending draft

Security
--------
- Read-only endpoints expose only structured draft data.
- No SMTP credentials ever appear in responses.
- All endpoints are tenant-scoped via X-Tenant-ID header.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.email_draft_models import EmailDraft
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/email/drafts", tags=["email-drafts"])



def _draft_to_dict(d: EmailDraft) -> dict:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "role_key": d.role_key,
        "recipients": json.loads(d.recipients_json or "[]"),
        "subject": d.subject,
        "body": d.body,
        "reply_to": d.reply_to,
        "purpose": d.purpose,
        "evidence_sources": json.loads(d.evidence_sources_json or "[]"),
        "status": d.status,
        "linked_plan_id": d.linked_plan_id,
        "linked_approval_id": d.linked_approval_id,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


@router.get("", response_model=list[dict])
async def list_drafts(
    limit: int = 20,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List recent email drafts for this tenant."""
    result = await db.execute(
        select(EmailDraft)
        .where(EmailDraft.tenant_id == tenant_id)
        .order_by(EmailDraft.created_at.desc())
        .limit(min(limit, 100))
    )
    return [_draft_to_dict(d) for d in result.scalars().all()]


@router.get("/{draft_id}", response_model=dict)
async def get_draft(
    draft_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a specific email draft."""
    result = await db.execute(
        select(EmailDraft).where(
            EmailDraft.id == draft_id,
            EmailDraft.tenant_id == tenant_id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found.")
    return _draft_to_dict(draft)


@router.post("/{draft_id}/cancel", response_model=dict)
async def cancel_draft(
    draft_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a pending email draft."""
    result = await db.execute(
        select(EmailDraft).where(
            EmailDraft.id == draft_id,
            EmailDraft.tenant_id == tenant_id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found.")
    if draft.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is already '{draft.status}' — cannot cancel.",
        )
    draft.status = "cancelled"
    await db.flush()
    return _draft_to_dict(draft)
