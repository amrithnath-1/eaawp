"""
Google OAuth 2.0 Router for Google Search Console Integration.

Phase 4 external integration proof — OAuth2 web server flow.

Endpoints:
  1. GET  /oauth/google/authorize
      → Generates a CSRF state token, stores it in oauth_states,
         redirects browser to Google's authorization endpoint.
      → Used by frontend "Connect" button (triggers browser redirect).

  2. GET  /oauth/google/callback
      → Google redirects back here after user authorisation.
      → Validates state token, exchanges code for access+refresh tokens.
      → Creates or updates integration_catalog row with encrypted tokens.
      → Redirects browser back to the frontend (with success/error status).

Security invariants:
  • State tokens are random, one-time-use, bound to tenant_id + integration_id.
  • Authorization code is exchanged server-side; never exposed to frontend JS.
  • Tokens are encrypted at rest (via IntegrationManager._encrypt_credentials).
  • Tenant identification comes from X-Tenant-ID header (set by frontend).
  • No secrets (client_secret, refresh_token) ever appear in URL parameters,
     logs, error messages, or API responses.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote, urlencode

import google_auth_oauthlib.flow
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.config import settings
from app.core.auth import as_utc, get_current_user
from app.db.models import User
from app.db.integration_models import Integration
from app.db.oauth_models import OAuthState
from app.integrations.integration_registry import integration_registry
from app.integrations.manager import (
    create_integration,
    get_integration,
    update_integration,
)
from app.schemas.integration_framework import (
    IntegrationCreate,
    IntegrationOut,
    IntegrationUpdate,
    OAuthAuthorizeResponse,
    OAuthCallbackResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Google OAuth2 configuration
_GSC_OAUTH_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_GA_OAUTH_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# Scopes and provider_type per OAuth provider
_PROVIDER_SCOPES: dict[str, list[str]] = {
    "google_search_console": _GSC_OAUTH_SCOPES,
    "google_analytics": _GA_OAUTH_SCOPES,
}
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "google_search_console": "Google Search Console",
    "google_analytics": "Google Analytics",
}

# Time after which OAuth state tokens expire and must be rejected.
_OAUTH_STATE_TTL_MINUTES = 10

# Frontend redirect URL after successful authorization.
# This must be a page that can display the connection status.
_FRONTEND_CALLBACK_PATH = "/integrations"


def _frontend_callback_path(provider_type: str) -> str:
    """Return the frontend path for a provider's post-auth redirect."""
    return f"/integrations?integration={provider_type}"


def _require_google_config() -> None:
    """Ensure Google OAuth credentials are configured. Returns 503 (not 500) when missing."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured on this server. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env.",
        )
    if not settings.google_redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_REDIRECT_URI is not configured on this server.",
        )


def _generate_state_token() -> str:
    """
    Generate a cryptographically random OAuth2 state token.

    Returns a 64‑character hex string (32 bytes of entropy).
    """
    return secrets.token_hex(32)


def _build_google_authorize(
    provider_type: str,
    tenant_id: str,
    integration_id: str,
    state_token: str,
    expires_at: datetime,
) -> str:
    """Build a Google OAuth2 authorization URL for the given provider."""
    scopes = _PROVIDER_SCOPES.get(provider_type, _GSC_OAUTH_SCOPES)
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=scopes,
    )
    flow.redirect_uri = settings.google_redirect_uri
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state_token,
    )
    return authorization_url


async def _google_authorize_common(
    provider_type: str,
    user: User,
    db: AsyncSession,
) -> OAuthAuthorizeResponse:
    """Shared logic for Google OAuth authorize (GSC and GA).

    The tenant and initiating user come from the verified JWT only.
    """
    tenant_id = user.tenant_id
    _require_google_config()

    provider = integration_registry.get(provider_type)
    if not provider:
        raise HTTPException(
            status_code=501,
            detail=f"{provider_type} integration is not available.",
        )

    # Purge stale OAuthState records for this tenant to avoid accumulation.
    # Only states older than the TTL are removed — active states are kept.
    try:
        from sqlalchemy import delete as sql_delete
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_OAUTH_STATE_TTL_MINUTES)
        await db.execute(
            sql_delete(OAuthState).where(
                OAuthState.tenant_id == tenant_id,
                OAuthState.expires_at < cutoff,
            )
        )
        await db.flush()
    except Exception as cleanup_exc:
        logger.debug("OAuthState cleanup failed (non-fatal): %s", cleanup_exc)

    display_name = _PROVIDER_DISPLAY_NAMES.get(provider_type, provider.display_name)

    # Create placeholder integration row
    integration = await create_integration(
        IntegrationCreate(
            provider_type=provider_type,
            display_name=display_name,
            credentials={},
        ),
        tenant_id=tenant_id,
        db=db,
    )

    # Generate and store CSRF state token
    state_token = _generate_state_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_OAUTH_STATE_TTL_MINUTES)

    oauth_state = OAuthState(
        state_token=state_token,
        tenant_id=tenant_id,
        initiated_by_user_id=user.id,
        integration_id=integration.id,
        provider_type=provider_type,
        expires_at=expires_at,
        used=False,
    )
    db.add(oauth_state)
    await db.commit()

    authorization_url = _build_google_authorize(
        provider_type=provider_type,
        tenant_id=tenant_id,
        integration_id=integration.id,
        state_token=state_token,
        expires_at=expires_at,
    )

    logger.info(
        "Google OAuth authorization initiated — provider=%s tenant=%s integration=%s",
        provider_type, tenant_id, integration.id,
    )

    return OAuthAuthorizeResponse(
        integration_id=integration.id,
        authorization_url=authorization_url,
        state_token=state_token,
        expires_at=expires_at.isoformat(),
    )


@router.get("/google/authorize", response_model=OAuthAuthorizeResponse)
async def google_authorize(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
) -> OAuthAuthorizeResponse:
    """
    Initiate Google OAuth2 web server flow for Google Search Console.
    Use /google/analytics/authorize for Google Analytics.
    """
    return await _google_authorize_common("google_search_console", user, db)


@router.get("/google/analytics/authorize", response_model=OAuthAuthorizeResponse)
async def google_analytics_authorize(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
) -> OAuthAuthorizeResponse:
    """
    Initiate Google OAuth2 web server flow for Google Analytics 4.
    Requests analytics.readonly scope.
    Both GSC and GA share the same Google OAuth client credentials.
    """
    return await _google_authorize_common("google_analytics", user, db)


@router.get("/google/callback", response_model=OAuthCallbackResponse)
async def google_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str | None, Query(description="OAuth2 authorization code")] = None,
    state: Annotated[str | None, Query(description="OAuth2 state token")] = None,
    error: Annotated[str | None, Query(description="OAuth2 error from Google")] = None,
    error_description: Annotated[
        str | None, Query(description="Human-readable error description")
    ] = None,
) -> RedirectResponse:
    """
    Google OAuth2 callback endpoint — handles authorization code exchange.

    This endpoint:
      1. Validates the state token (CSRF protection).
      2. Ensures the state is not expired and has not been used.
      3. Exchanges the authorization code for an access token + refresh token.
      4. Encrypts the tokens and stores them in integration_catalog.
      5. Marks the OAuthState as used.
      6. Updates integration status to "connected" and enables it.
      7. Redirects the browser back to the frontend with success/error query params.

    Security note: The authorization code is single-use and short-lived.
    This endpoint must be called within minutes of the user's authorization.
    """
    _require_google_config()

    # 1. Google may return an error (e.g., user denied permission)
    if error:
        logger.warning(
            "Google OAuth callback error: %s (%s)",
            error,
            error_description or "no description",
        )
        # Redirect to frontend with error parameters
        frontend_url = _build_frontend_redirect(error=error, error_description=error_description)
        return RedirectResponse(url=frontend_url, status_code=302)

    # 2. Validate required parameters
    if not code:
        frontend_url = _build_frontend_redirect(error="missing_code", error_description="No authorization code received from Google.")
        return RedirectResponse(url=frontend_url, status_code=302)
    if not state:
        frontend_url = _build_frontend_redirect(error="missing_state", error_description="No state token received from Google.")
        return RedirectResponse(url=frontend_url, status_code=302)

    # 3. Look up the OAuthState record
    stmt = select(OAuthState).where(
        OAuthState.state_token == state,
        OAuthState.used == False,
    )
    result = await db.execute(stmt)
    oauth_state = result.scalar_one_or_none()

    if not oauth_state:
        logger.warning("OAuth callback rejected: unknown or already used state token")
        frontend_url = _build_frontend_redirect(error="invalid_state", error_description="Invalid or expired OAuth state token.")
        return RedirectResponse(url=frontend_url, status_code=302)

    # 4. Check expiration
    now = datetime.now(timezone.utc)
    if as_utc(oauth_state.expires_at) < now:
        logger.warning("OAuth callback rejected: expired state token (tenant=%s)", oauth_state.tenant_id)
        frontend_url = _build_frontend_redirect(error="expired_state", error_description="OAuth state token has expired.")
        return RedirectResponse(url=frontend_url, status_code=302)

    # 4b. The flow must belong to a user who is still active in the same
    #     tenant.  The callback carries no Bearer token (it is a browser
    #     redirect from Google), so this server-side binding is the check.
    initiator = None
    if oauth_state.initiated_by_user_id:
        initiator_result = await db.execute(
            select(User).where(
                User.id == oauth_state.initiated_by_user_id,
                User.tenant_id == oauth_state.tenant_id,
                User.is_active == True,  # noqa: E712
            )
        )
        initiator = initiator_result.scalar_one_or_none()
    if initiator is None:
        oauth_state.used = True  # burn the state; the user must restart the flow
        db.add(oauth_state)
        await db.commit()
        logger.warning(
            "OAuth callback rejected: no active initiating user (tenant=%s)",
            oauth_state.tenant_id,
        )
        frontend_url = _build_frontend_redirect(
            error="invalid_state",
            error_description="Invalid or expired OAuth state token.",
        )
        return RedirectResponse(url=frontend_url, status_code=302)

    # 5. Mark state as used (defend against replay attacks)
    oauth_state.used = True
    db.add(oauth_state)
    await db.commit()

    tenant_id = oauth_state.tenant_id
    integration_id = oauth_state.integration_id

    # 6. Exchange authorization code for tokens
    try:
        # Use the scopes registered for the provider_type stored in the OAuth state
        provider_type = oauth_state.provider_type
        scopes = _PROVIDER_SCOPES.get(provider_type, _GSC_OAUTH_SCOPES)

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=scopes,
        )
        flow.redirect_uri = settings.google_redirect_uri

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: flow.fetch_token(code=code),
        )

        # 7. Build credentials dict for encryption
        credentials = {
            "access_token": flow.credentials.token,
            "refresh_token": flow.credentials.refresh_token,
            "token_expiry": flow.credentials.expiry.isoformat() if flow.credentials.expiry else None,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        }

        # 8. Update integration_catalog with encrypted credentials
        integration_update = IntegrationUpdate(
            credentials=credentials,  # will be encrypted by manager
            is_enabled=True,
        )
        await update_integration(
            integration_id=integration_id,
            body=integration_update,
            tenant_id=tenant_id,
            db=db,
        )

        logger.info(
            "Google OAuth callback succeeded — provider=%s tenant=%s integration=%s",
            provider_type,
            tenant_id,
            integration_id,
        )

        # 9. Auto-test the connection now that tokens are stored.
        #    This moves the integration from "not_tested" → "connected" immediately,
        #    so the frontend shows an accurate status without requiring a manual test.
        try:
            from app.integrations.manager import test_integration as mgr_test
            test_result = await mgr_test(integration_id, tenant_id, db)
            if test_result.success:
                logger.info(
                    "Post-OAuth auto-test succeeded — provider=%s integration=%s",
                    provider_type, integration_id,
                )
            else:
                logger.warning(
                    "Post-OAuth auto-test failed (tokens stored, connection check failed) "
                    "— provider=%s integration=%s error=%s",
                    provider_type, integration_id, test_result.error_message,
                )
        except Exception as test_exc:
            # Non-fatal — tokens are already stored; user can test manually
            logger.warning(
                "Post-OAuth auto-test raised an exception (non-fatal): %s", test_exc
            )

        # 10. Write an audit log entry for the successful OAuth connection
        try:
            import uuid as _uuid_mod
            from app.db.models import AuditLog
            audit = AuditLog(
                id=str(_uuid_mod.uuid4()),
                tenant_id=tenant_id,
                actor="oauth_callback",
                event=f"oauth.connected: provider={provider_type} integration_id={integration_id}",
                department="integrations",
                status="ok",
            )
            db.add(audit)
            await db.commit()
        except Exception as audit_exc:
            logger.warning("OAuth audit write failed (non-fatal): %s", audit_exc)

        # 11. Redirect to frontend with success parameters
        frontend_url = _build_frontend_redirect(
            success="true",
            integration_id=integration_id,
            provider_type=provider_type,
        )
        return RedirectResponse(url=frontend_url, status_code=302)

    except Exception as exc:
        logger.exception(
            "Google OAuth token exchange failed for tenant %s, integration %s",
            tenant_id,
            integration_id,
        )
        frontend_url = _build_frontend_redirect(
            error="token_exchange_failed",
            error_description="Failed to exchange authorization code for tokens.",
        )
        return RedirectResponse(url=frontend_url, status_code=302)


def _build_frontend_redirect(**params: str | None) -> str:
    """
    Build a frontend redirect URL with query parameters.
    Uses the provider_type param to determine the landing path.
    """
    base = settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:5173"
    provider_type = params.get("provider_type", "")
    path = _frontend_callback_path(provider_type) if provider_type else _FRONTEND_CALLBACK_PATH
    url = base.rstrip("/") + path
    # Add non‑None parameters (skip provider_type — it's already in the path)
    query = {k: v for k, v in params.items() if v is not None and k != "provider_type"}
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query, quote_via=quote)
    return url
