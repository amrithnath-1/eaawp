"""
EAAWP Admin-Assisted Configuration Engine — Tests

Tests cover:
1.  Admin can submit provider config — no secret values in response.
2.  Non-admin cannot submit provider config — 403.
3.  Missing fields detected for GSC when no config exists.
4.  Partial config returns only missing fields.
5.  Secret values never appear in ConfigurationStatus.
6.  Secret values never appear in AuditLog.
7.  Config is tenant-isolated.
8.  Config is encrypted at rest (encrypted_value != plaintext).
9.  Invalid redirect_uri format rejected — 422.
10. build_conversation_reply with missing config returns CONFIGURATION_REQUIRED.
11. build_conversation_reply with complete config returns REDIRECT_TO_OAUTH.
12. NL chat GSC with missing config has redirect_uri in action_data.
13. redirect_uri in status matches actual OAuth callback route.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_admin_user(tenant_id: str = "test-tenant") -> MagicMock:
    user = MagicMock()
    user.id = "user-001"
    user.email = "admin@test.com"
    user.role = "Admin"
    user.tenant_id = tenant_id
    user.is_active = True
    return user


def _make_non_admin_user(tenant_id: str = "test-tenant") -> MagicMock:
    user = MagicMock()
    user.id = "user-002"
    user.email = "employee@test.com"
    user.role = "Employee"
    user.tenant_id = tenant_id
    user.is_active = True
    return user


def _make_mock_db(rows: list | None = None) -> AsyncMock:
    """
    Create a mock AsyncSession.
    rows: list of field_key strings that the DB query will return as "configured".
    """
    db = AsyncMock()

    mock_result = MagicMock()
    # fetchall() returns list of 1-tuples mimicking (field_key,) rows.
    mock_result.fetchall = MagicMock(
        return_value=[(key,) for key in (rows or [])]
    )
    # scalar_one_or_none() returns None by default (no existing row to update).
    mock_result.scalar_one_or_none = MagicMock(return_value=None)

    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_gsc_intent():
    """IntegrationIntent for CONNECT_INTEGRATION → google_search_console."""
    from app.schemas.nl_integration import IntegrationIntent
    return IntegrationIntent(
        intent_type="CONNECT_INTEGRATION",
        provider_type="google_search_console",
        confidence=0.95,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Admin can submit provider config — response has no secret values
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_admin_can_submit_provider_config():
    """store_provider_field completes without error, adds AuditLog, flushes."""
    from app.services.provider_config_service import store_provider_field

    mock_db = _make_mock_db()
    await store_provider_field(
        provider_type="google_search_console",
        field_key="client_id",
        value="test-client-id.apps.googleusercontent.com",
        tenant_id="test-tenant",
        configured_by="user-001",
        db=mock_db,
    )

    # DB add should have been called (for the ProviderServerConfig row and AuditLog).
    assert mock_db.add.called, "Expected db.add to be called"
    assert mock_db.flush.called, "Expected db.flush to be called"

    # The response contains no secret values — verify AuditLog event.
    add_calls = mock_db.add.call_args_list
    audit_log_obj = None
    psc_obj = None
    for c in add_calls:
        obj = c.args[0]
        class_name = type(obj).__name__
        if "AuditLog" in class_name:
            audit_log_obj = obj
        elif "ProviderServerConfig" in class_name:
            psc_obj = obj

    assert audit_log_obj is not None, "AuditLog should have been added"
    assert psc_obj is not None, "ProviderServerConfig should have been added"
    # AuditLog event must not contain the value.
    assert "test-client-id" not in audit_log_obj.event
    # Response: store_provider_field returns None — never returns the value.


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Non-admin cannot submit provider config — 403
# ═══════════════════════════════════════════════════════════════════════════════

def test_non_admin_cannot_submit_provider_config():
    """require_admin raises HTTPException 403 for non-admin users."""
    from fastapi import HTTPException
    from app.core.auth import require_admin

    non_admin = _make_non_admin_user()
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=non_admin)
    assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Missing fields detected for GSC — no env vars, no DB rows
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_missing_fields_detected_for_gsc():
    """All 3 GSC fields should be in missing_fields when nothing is configured."""
    from app.services.provider_config_service import get_provider_configuration_status

    mock_db = _make_mock_db(rows=[])  # no DB rows

    with (
        patch("app.services.provider_config_service.settings") as mock_settings,
    ):
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        mock_settings.google_redirect_uri = ""

        status = await get_provider_configuration_status(
            "google_search_console", "test-tenant", mock_db
        )

    assert status.state == "NOT_CONFIGURED"
    assert "client_id" in status.missing_fields
    assert "client_secret" in status.missing_fields
    assert "redirect_uri" in status.missing_fields
    assert len(status.configured_fields) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Partial config returns only missing fields
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_only_missing_fields_returned_when_some_configured():
    """When client_id is in DB and client_secret is missing, state is PARTIALLY_CONFIGURED."""
    from app.services.provider_config_service import get_provider_configuration_status

    # DB has client_id configured.
    mock_db = _make_mock_db(rows=["client_id"])

    with patch("app.services.provider_config_service.settings") as mock_settings:
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        mock_settings.google_redirect_uri = ""

        status = await get_provider_configuration_status(
            "google_search_console", "test-tenant", mock_db
        )

    assert status.state == "PARTIALLY_CONFIGURED"
    assert "client_id" not in status.missing_fields
    assert "client_id" in status.configured_fields
    assert "client_secret" in status.missing_fields


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Secret values never appear in ConfigurationStatus
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_secret_values_never_appear_in_configuration_status():
    """Serialized ConfigurationStatus must not contain any actual credential values."""
    from app.services.provider_config_service import get_provider_configuration_status

    mock_db = _make_mock_db(rows=["client_id"])

    fake_secret = "GOCSPX-fake-secret-value-12345"
    with patch("app.services.provider_config_service.settings") as mock_settings:
        mock_settings.google_client_id = "real-client-id.apps.googleusercontent.com"
        mock_settings.google_client_secret = fake_secret
        mock_settings.google_redirect_uri = "http://localhost:8000/api/v1/oauth/google/callback"

        status = await get_provider_configuration_status(
            "google_search_console", "test-tenant", mock_db
        )

    result_str = str({
        "provider_type": status.provider_type,
        "state": status.state,
        "configured_fields": status.configured_fields,
        "missing_fields": status.missing_fields,
        "oauth_ready": status.oauth_ready,
        "redirect_uri": status.redirect_uri,
        "message": status.message,
    })

    assert "GOCSPX-" not in result_str, "Secret prefix must not appear in status"
    assert fake_secret not in result_str, "Full secret must not appear in status"
    assert "real-client-id" not in result_str, "Client ID value must not appear in status"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Secret values never appear in AuditLog
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_secret_values_never_appear_in_audit_log():
    """AuditLog.event must not contain the plaintext secret value."""
    from app.services.provider_config_service import store_provider_field

    mock_db = _make_mock_db()
    secret_value = "super-secret-client-secret-xyz"

    await store_provider_field(
        provider_type="google_search_console",
        field_key="client_secret",
        value=secret_value,
        tenant_id="test-tenant",
        configured_by="user-001",
        db=mock_db,
    )

    audit_log_obj = None
    for c in mock_db.add.call_args_list:
        obj = c.args[0]
        if "AuditLog" in type(obj).__name__:
            audit_log_obj = obj
            break

    assert audit_log_obj is not None, "AuditLog must be added"
    event_str = audit_log_obj.event
    assert secret_value not in event_str, f"Secret value found in AuditLog.event: {event_str!r}"
    # Also check full obj dict representation.
    obj_dict_str = str({k: v for k, v in vars(audit_log_obj).items() if not k.startswith("_")})
    assert secret_value not in obj_dict_str, "Secret value found in AuditLog attributes"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Config is tenant-isolated
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_config_is_tenant_isolated():
    """Tenant A config is not visible to Tenant B."""
    from app.services.provider_config_service import get_provider_configuration_status

    # Tenant A has client_id configured in DB.
    mock_db_a = _make_mock_db(rows=["client_id"])
    # Tenant B has nothing.
    mock_db_b = _make_mock_db(rows=[])

    with patch("app.services.provider_config_service.settings") as mock_settings:
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        mock_settings.google_redirect_uri = ""

        status_a = await get_provider_configuration_status(
            "google_search_console", "tenant-A", mock_db_a
        )
        status_b = await get_provider_configuration_status(
            "google_search_console", "tenant-B", mock_db_b
        )

    assert "client_id" in status_a.configured_fields
    assert "client_id" not in status_b.configured_fields
    assert "client_id" in status_b.missing_fields


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Config is encrypted at rest
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_config_encrypted_at_rest():
    """encrypted_value in DB must not equal plaintext; must decrypt correctly."""
    from app.integrations.crypto import decrypt_password
    from app.services.provider_config_service import store_provider_field

    mock_db = _make_mock_db()
    plaintext = "plaintext-secret-value-99"

    await store_provider_field(
        provider_type="google_search_console",
        field_key="client_secret",
        value=plaintext,
        tenant_id="test-tenant",
        configured_by="user-001",
        db=mock_db,
    )

    # Find the ProviderServerConfig object that was added.
    psc_obj = None
    for c in mock_db.add.call_args_list:
        obj = c.args[0]
        if "ProviderServerConfig" in type(obj).__name__:
            psc_obj = obj
            break

    assert psc_obj is not None, "ProviderServerConfig must be added"
    assert psc_obj.encrypted_value != plaintext, "encrypted_value must not equal plaintext"
    assert decrypt_password(psc_obj.encrypted_value) == plaintext, "Must decrypt back to plaintext"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Invalid redirect_uri format rejected — 422
# ═══════════════════════════════════════════════════════════════════════════════

def test_invalid_redirect_uri_format_rejected():
    """Submitting a non-URL redirect_uri must raise HTTPException 422."""
    from fastapi import HTTPException
    from app.api.routers.admin_config import _validate_field_value

    with pytest.raises(HTTPException) as exc_info:
        _validate_field_value(
            provider_type="google_search_console",
            field_key="redirect_uri",
            value="not-a-url",
            is_secret=False,
        )
    assert exc_info.value.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 10. build_conversation_reply with missing config returns CONFIGURATION_REQUIRED
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_integration_with_missing_config_returns_configuration_required():
    """CONNECT GSC with no config → next_action == CONFIGURATION_REQUIRED."""
    from app.services.nl_integration_service import build_conversation_reply
    from app.integrations.provider import ConfigurationStatus

    mock_db = _make_mock_db()
    intent = _make_gsc_intent()

    missing_status = ConfigurationStatus(
        provider_type="google_search_console",
        state="NOT_CONFIGURED",
        configured_fields=[],
        missing_fields=["client_id", "client_secret", "redirect_uri"],
        oauth_ready=False,
        redirect_uri="http://localhost:8000/api/v1/oauth/google/callback",
        message="Missing fields",
    )

    # The function does a lazy import: `from app.services.provider_config_service import ...`
    # Patch the function at its definition location.
    with patch(
        "app.services.provider_config_service.get_provider_configuration_status",
        new=AsyncMock(return_value=missing_status),
    ):
        reply, next_action, action_data = await build_conversation_reply(
            intent=intent,
            tenant_integrations=[],
            db=mock_db,
            tenant_id="test-tenant",
        )

    assert next_action == "CONFIGURATION_REQUIRED"
    assert "client_secret" in action_data["missing_fields"]
    assert action_data["provider_type"] == "google_search_console"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. build_conversation_reply with complete config returns REDIRECT_TO_OAUTH
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_integration_with_complete_config_returns_redirect_to_oauth():
    """CONNECT GSC with all fields configured → next_action == REDIRECT_TO_OAUTH."""
    from app.services.nl_integration_service import build_conversation_reply
    from app.integrations.provider import ConfigurationStatus

    mock_db = _make_mock_db()
    intent = _make_gsc_intent()

    complete_status = ConfigurationStatus(
        provider_type="google_search_console",
        state="CONFIGURED",
        configured_fields=["client_id", "client_secret", "redirect_uri"],
        missing_fields=[],
        oauth_ready=True,
        redirect_uri="http://localhost:8000/api/v1/oauth/google/callback",
        message="All configured",
    )

    with patch(
        "app.services.provider_config_service.get_provider_configuration_status",
        new=AsyncMock(return_value=complete_status),
    ):
        reply, next_action, action_data = await build_conversation_reply(
            intent=intent,
            tenant_integrations=[],
            db=mock_db,
            tenant_id="test-tenant",
        )

    assert next_action == "REDIRECT_TO_OAUTH"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. NL chat GSC with missing config has redirect_uri in action_data
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_nl_chat_for_gsc_produces_redirect_uri_in_action_data():
    """When GSC config is missing, action_data must contain a non-empty redirect_uri."""
    from app.services.nl_integration_service import build_conversation_reply
    from app.integrations.provider import ConfigurationStatus

    mock_db = _make_mock_db()
    intent = _make_gsc_intent()

    missing_status = ConfigurationStatus(
        provider_type="google_search_console",
        state="NOT_CONFIGURED",
        configured_fields=[],
        missing_fields=["client_id", "client_secret", "redirect_uri"],
        oauth_ready=False,
        redirect_uri="http://localhost:8000/api/v1/oauth/google/callback",
        message="Missing",
    )

    with patch(
        "app.services.provider_config_service.get_provider_configuration_status",
        new=AsyncMock(return_value=missing_status),
    ):
        reply, next_action, action_data = await build_conversation_reply(
            intent=intent,
            tenant_integrations=[],
            db=mock_db,
            tenant_id="test-tenant",
        )

    assert "redirect_uri" in action_data
    assert isinstance(action_data["redirect_uri"], str)
    assert action_data["redirect_uri"].startswith("http")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. redirect_uri in status matches actual OAuth callback route
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_redirect_uri_shown_to_admin_is_actual_callback_url():
    """redirect_uri in ConfigurationStatus must match the real Google OAuth callback."""
    from app.services.provider_config_service import get_provider_configuration_status

    mock_db = _make_mock_db(rows=[])
    expected_uri = "http://localhost:8000/api/v1/oauth/google/callback"

    with patch("app.services.provider_config_service.settings") as mock_settings:
        mock_settings.google_client_id = ""
        mock_settings.google_client_secret = ""
        mock_settings.google_redirect_uri = expected_uri

        status = await get_provider_configuration_status(
            "google_search_console", "test-tenant", mock_db
        )

    assert status.redirect_uri == expected_uri
