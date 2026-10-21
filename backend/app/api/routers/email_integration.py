"""
EAAWP Email Integration Router

Manages SMTP email integration configuration per tenant.

Endpoints
---------
POST   /api/v1/email/integration           — create/replace SMTP config
GET    /api/v1/email/integration           — get safe integration status
PATCH  /api/v1/email/integration           — update SMTP config
DELETE /api/v1/email/integration           — remove integration
POST   /api/v1/email/integration/test      — test SMTP connection
POST   /api/v1/email/integration/enable    — enable integration
POST   /api/v1/email/integration/disable   — disable integration
GET    /api/v1/email/audit                 — get email audit log

Security
--------
- encrypted_password is NEVER returned in any response.
- All endpoints are tenant-scoped via X-Tenant-ID header.
- Only the connection test uses a live SMTP connection.
- Audit log records safe metadata only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.email_models import EmailAuditLog, ExternalIntegration
from app.db.session import get_db
from app.integrations.crypto import encrypt_password
from app.integrations.email_provider import SMTPEmailProvider
from app.schemas.email_integration import (
    ConnectionTestResultOut,
    EmailIntegrationOut,
    IntegrationStatus,
    SMTPConfigCreate,
    SMTPConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/email", tags=["email-integration"])



def _integration_to_out(i: ExternalIntegration) -> EmailIntegrationOut:
    """Convert ORM row to safe output schema — never exposes password."""
    # Create a password hint: first + last char of username as proxy,
    # or just "••••••" to confirm a password is set
    hint = "••••••" if i.encrypted_password else "(not set)"
    return EmailIntegrationOut(
        id=i.id,
        tenant_id=i.tenant_id,
        provider_type=i.provider_type,
        display_name=i.display_name,
        smtp_host=i.smtp_host,
        smtp_port=i.smtp_port,
        username=i.username,
        password_hint=hint,
        tls_mode=i.tls_mode,
        sender_email=i.sender_email,
        sender_display_name=i.sender_display_name,
        status=i.status,  # type: ignore[arg-type]
        is_enabled=i.is_enabled,
        last_tested_at=i.last_tested_at.isoformat() if i.last_tested_at else None,
        error_message=i.error_message,
        created_by=i.created_by,
        created_at=i.created_at.isoformat(),
        updated_at=i.updated_at.isoformat(),
    )


async def _get_integration(
    tenant_id: str, db: AsyncSession
) -> ExternalIntegration | None:
    result = await db.execute(
        select(ExternalIntegration).where(
            ExternalIntegration.tenant_id == tenant_id,
            ExternalIntegration.provider_type == "smtp",
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _require_integration(
    tenant_id: str, db: AsyncSession
) -> ExternalIntegration:
    integration = await _get_integration(tenant_id, db)
    if not integration:
        raise HTTPException(
            status_code=404,
            detail="No SMTP integration configured for this tenant.",
        )
    return integration


# ── Create / replace ──────────────────────────────────────────────────────────

@router.post("/integration", response_model=EmailIntegrationOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_email_integration(
    body: SMTPConfigCreate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmailIntegrationOut:
    """
    Create or replace the tenant's SMTP integration.
    The password is encrypted immediately and never stored plain.
    """
    existing = await _get_integration(tenant_id, db)

    encrypted = encrypt_password(body.password)

    if existing:
        # Replace existing config
        existing.display_name = body.display_name
        existing.smtp_host = body.smtp_host
        existing.smtp_port = body.smtp_port
        existing.username = body.username
        existing.encrypted_password = encrypted
        existing.tls_mode = body.tls_mode
        existing.sender_email = body.sender_email
        existing.sender_display_name = body.sender_display_name
        existing.status = "not_tested"
        existing.error_message = None
        existing.last_tested_at = None
        await db.flush()
        return _integration_to_out(existing)

    integration = ExternalIntegration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider_type="smtp",
        display_name=body.display_name,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        username=body.username,
        encrypted_password=encrypted,
        tls_mode=body.tls_mode,
        sender_email=body.sender_email,
        sender_display_name=body.sender_display_name,
        status="not_tested",
        is_enabled=True,
        created_by=body.created_by,
    )
    db.add(integration)
    await db.flush()
    logger.info("SMTP integration created for tenant %s", tenant_id)
    return _integration_to_out(integration)


# ── Get status ────────────────────────────────────────────────────────────────

@router.get("/integration", response_model=EmailIntegrationOut)
async def get_email_integration(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmailIntegrationOut:
    """Get the safe integration status. Password is never returned."""
    integration = await _require_integration(tenant_id, db)
    return _integration_to_out(integration)


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/integration", response_model=EmailIntegrationOut, dependencies=[Depends(require_admin)])
async def update_email_integration(
    body: SMTPConfigUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmailIntegrationOut:
    """Partially update the SMTP integration. If password is provided, it is re-encrypted."""
    integration = await _require_integration(tenant_id, db)

    if body.display_name is not None:
        integration.display_name = body.display_name
    if body.smtp_host is not None:
        integration.smtp_host = body.smtp_host
        integration.status = "not_tested"
    if body.smtp_port is not None:
        integration.smtp_port = body.smtp_port
        integration.status = "not_tested"
    if body.username is not None:
        integration.username = body.username
        integration.status = "not_tested"
    if body.password is not None:
        integration.encrypted_password = encrypt_password(body.password)
        integration.status = "not_tested"
    if body.tls_mode is not None:
        integration.tls_mode = body.tls_mode
        integration.status = "not_tested"
    if body.sender_email is not None:
        integration.sender_email = body.sender_email
    if body.sender_display_name is not None:
        integration.sender_display_name = body.sender_display_name

    await db.flush()
    return _integration_to_out(integration)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/integration", response_model=None, status_code=204, dependencies=[Depends(require_admin)])
async def delete_email_integration(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the SMTP integration. All audit logs are preserved."""
    integration = await _require_integration(tenant_id, db)
    await db.delete(integration)
    await db.flush()
    logger.info("SMTP integration deleted for tenant %s", tenant_id)


# ── Test connection ───────────────────────────────────────────────────────────

@router.post("/integration/test", response_model=ConnectionTestResultOut, dependencies=[Depends(require_admin)])
async def test_email_integration(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ConnectionTestResultOut:
    """
    Test the SMTP connection without sending an email.
    Updates the integration status based on the result.
    Never returns credentials in the response.
    """
    integration = await _require_integration(tenant_id, db)

    integration.status = "not_tested"
    await db.flush()

    try:
        provider = SMTPEmailProvider(integration)
        result = await provider.test_connection()
    except Exception as exc:
        logger.error("SMTP test error for tenant %s: %s", tenant_id, exc)
        integration.status = "failed"
        integration.error_message = str(exc)[:300]
        integration.last_tested_at = datetime.now(timezone.utc)
        await db.flush()
        return ConnectionTestResultOut(
            integration_id=integration.id,
            success=False,
            status="failed",
            error_message="Connection test encountered an unexpected error.",
        )

    integration.status = "connected" if result.success else "failed"
    integration.last_tested_at = datetime.now(timezone.utc)
    integration.error_message = result.error_message if not result.success else None
    await db.flush()

    return ConnectionTestResultOut(
        integration_id=integration.id,
        success=result.success,
        status=integration.status,  # type: ignore[arg-type]
        server_greeting=result.server_greeting if result.success else None,
        error_message=result.error_message if not result.success else None,
    )


# ── Enable / disable ──────────────────────────────────────────────────────────

@router.post("/integration/enable", response_model=EmailIntegrationOut, dependencies=[Depends(require_admin)])
async def enable_email_integration(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmailIntegrationOut:
    integration = await _require_integration(tenant_id, db)
    integration.is_enabled = True
    await db.flush()
    return _integration_to_out(integration)


@router.post("/integration/disable", response_model=EmailIntegrationOut, dependencies=[Depends(require_admin)])
async def disable_email_integration(
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmailIntegrationOut:
    integration = await _require_integration(tenant_id, db)
    integration.is_enabled = False
    await db.flush()
    return _integration_to_out(integration)


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=list[dict])
async def get_email_audit(
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Get the email send audit log for this tenant.
    Returns safe metadata only — no credentials, no full body.
    """
    result = await db.execute(
        select(EmailAuditLog)
        .where(EmailAuditLog.tenant_id == tenant_id)
        .order_by(EmailAuditLog.attempted_at.desc())
        .limit(min(limit, 200))
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "role_key": r.role_key,
            "integration_id": r.integration_id,
            "recipient_count": r.recipient_count,
            "recipient_domains": r.recipient_domains,
            "subject_length": r.subject_length,
            "body_length": r.body_length,
            "success": r.success,
            "provider_message_id": r.provider_message_id,
            "error_message": r.error_message,
            "attempted_at": r.attempted_at.isoformat(),
        }
        for r in rows
    ]
