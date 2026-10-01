"""EAAWP Marketing Channel Service — tenant-scoped."""
from __future__ import annotations
import json, logging, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.channel_models import MarketingChannelIntegration
from app.integrations.channel_providers import get_provider
from app.integrations.crypto import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)


def _to_safe_dict(c: MarketingChannelIntegration) -> dict:
    """Never returns encrypted_credentials."""
    return {
        "id": c.id, "tenant_id": c.tenant_id,
        "channel_type": c.channel_type, "display_name": c.display_name,
        "provider": c.provider, "status": c.status, "is_enabled": c.is_enabled,
        "capabilities": json.loads(c.capabilities_json or "[]"),
        "account_info": json.loads(c.account_info_json or "{}"),
        "last_tested_at": c.last_tested_at.isoformat() if c.last_tested_at else None,
        "error_message": c.error_message,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat(),
    }


async def create_channel_integration(
    tenant_id: str, channel_type: str, display_name: str,
    provider: str, credentials: dict, db: AsyncSession, created_by: str = "admin",
) -> dict:
    encrypted = encrypt_password(json.dumps(credentials)) if credentials else ""
    item = MarketingChannelIntegration(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        channel_type=channel_type, display_name=display_name,
        provider=provider, encrypted_credentials=encrypted,
        created_by=created_by,
    )
    db.add(item)
    await db.flush()
    return _to_safe_dict(item)


async def list_channel_integrations(tenant_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(MarketingChannelIntegration)
        .where(MarketingChannelIntegration.tenant_id == tenant_id)
        .order_by(MarketingChannelIntegration.created_at.desc())
    )
    return [_to_safe_dict(c) for c in result.scalars().all()]


async def test_channel_integration(integration_id: str, tenant_id: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(MarketingChannelIntegration).where(
            MarketingChannelIntegration.id == integration_id,
            MarketingChannelIntegration.tenant_id == tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"success": False, "error": "Integration not found."}

    try:
        credentials = json.loads(decrypt_password(item.encrypted_credentials)) if item.encrypted_credentials else {}
    except Exception:
        credentials = {}

    provider = get_provider(item.provider, item.channel_type)
    test_result = await provider.validate_connection(credentials)

    item.status = "connected" if test_result.success else "failed"
    item.last_tested_at = datetime.now(timezone.utc)
    item.error_message = test_result.error_message if not test_result.success else None
    if test_result.success:
        item.account_info_json = json.dumps(test_result.account_info)
        item.capabilities_json = json.dumps(test_result.capabilities)
    await db.flush()
    return {"success": test_result.success, "account_info": test_result.account_info,
            "capabilities": test_result.capabilities, "error": test_result.error_message}


async def enable_disable_channel(integration_id: str, tenant_id: str, enabled: bool, db: AsyncSession) -> dict | None:
    result = await db.execute(
        select(MarketingChannelIntegration).where(
            MarketingChannelIntegration.id == integration_id,
            MarketingChannelIntegration.tenant_id == tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return None
    item.is_enabled = enabled
    await db.flush()
    return _to_safe_dict(item)


async def prepare_content_for_channel(
    integration_id: str, tenant_id: str, content: dict, db: AsyncSession,
) -> dict:
    result = await db.execute(
        select(MarketingChannelIntegration).where(
            MarketingChannelIntegration.id == integration_id,
            MarketingChannelIntegration.tenant_id == tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"success": False, "error": "Integration not found."}
    if not item.is_enabled:
        return {"success": False, "error": "Integration is disabled."}

    provider = get_provider(item.provider, item.channel_type)
    channel_config = json.loads(item.account_info_json or "{}")
    prep_result = await provider.prepare_content(content, channel_config)
    return {
        "success": prep_result.success,
        "prepared_content": prep_result.prepared_content,
        "warnings": prep_result.validation_warnings,
        "error": prep_result.error_message,
    }
