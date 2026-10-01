"""
EAAWP Authentication Router

POST /api/v1/auth/token    — login with email + password → access + refresh tokens
POST /api/v1/auth/refresh  — exchange refresh token → new access token
GET  /api/v1/auth/me       — return current user profile (from JWT)

Security invariants:
- Passwords never appear in responses or logs.
- Tokens never appear in logs.
- Failed logins return the same 401 response regardless of whether the
  email exists (prevents user enumeration).
- Refresh tokens are JWT-signed; production should add a revocation store.
- The company_id (tenant_id) is part of the login request because users are
  scoped to a tenant — same email can exist in different companies.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_current_user,
    _decode_token,
    persist_refresh_token,
    validate_refresh_token_db,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
)
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Login with email, password, and company_id (tenant)."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password — never stored in plain text")
    company_id: str = Field(..., description="The tenant/company ID this user belongs to")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    tenant_id: str
    user_id: str
    user_name: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    user_id: str
    email: str
    name: str
    tenant_id: str
    role: str
    is_active: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse, summary="Login — obtain JWT tokens")
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate a user and issue JWT access + refresh tokens.

    The company_id (tenant_id) is required because users are tenant-scoped.
    Returns 401 for any authentication failure — does not distinguish between
    wrong email, wrong password, or inactive account.
    """
    user = await authenticate_user(
        email=body.email,
        password=body.password,
        tenant_id=body.company_id,
        db=db,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.config import settings
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    refresh_token = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
    )

    # Persist refresh token hash to DB for revocation support
    await persist_refresh_token(
        raw_token=refresh_token,
        user_id=user.id,
        tenant_id=user.tenant_id,
        db=db,
    )
    await db.commit()

    logger.info(
        "Login successful for user_id=%s tenant_id=%s role=%s",
        user.id, user.tenant_id, user.role,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in_seconds=settings.access_token_expire_minutes * 60,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user_name=user.name,
        role=user.role,
    )


@router.post("/token/form", response_model=TokenResponse, include_in_schema=False)
async def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    OAuth2 password flow form endpoint (used by Swagger UI /docs).
    Expects username=<email>|<company_id> to carry both values in one field.
    Format: username = "email@example.com|<company_id>"
    """
    parts = form.username.split("|", 1)
    email = parts[0].strip()
    company_id = parts[1].strip() if len(parts) > 1 else "default-tenant"
    proxy = LoginRequest(email=email, password=form.password, company_id=company_id)
    return await login(body=proxy, db=db)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token_endpoint(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access token + rotated refresh token.

    Validates the presented refresh token against the DB:
    - Token must exist (was issued by this server)
    - Token must not be revoked
    - Token must not be expired

    The old refresh token is revoked after issuing new tokens (rotation).
    This prevents replay attacks: a stolen token can only be used once.
    """
    from app.config import settings
    from sqlalchemy import select

    # Validate against DB (raises 401 if invalid/revoked/expired)
    payload = await validate_refresh_token_db(body.refresh_token, db)

    user_id: str | None = payload.get("sub")
    old_jti: str | None = payload.get("jti")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # Rotate: revoke the old token
    if old_jti:
        await revoke_refresh_token(old_jti, db)

    # Issue new tokens
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    new_refresh = create_refresh_token(user_id=user.id, tenant_id=user.tenant_id)

    # Persist new refresh token
    await persist_refresh_token(
        raw_token=new_refresh,
        user_id=user.id,
        tenant_id=user.tenant_id,
        db=db,
    )
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in_seconds=settings.access_token_expire_minutes * 60,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user_name=user.name,
        role=user.role,
    )


@router.post("/logout", status_code=204, response_model=None, summary="Logout — revoke refresh token")
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Revoke the presented refresh token (logout this device).
    If the token is already invalid/revoked, returns 204 silently
    (idempotent — prevents enumeration of token validity).
    """
    try:
        payload = await validate_refresh_token_db(body.refresh_token, db)
        jti = payload.get("jti")
        if jti:
            await revoke_refresh_token(jti, db)
            await db.commit()
    except HTTPException:
        pass  # Already invalid — silently succeed


@router.post("/logout/all", status_code=204, response_model=None, summary="Logout all devices")
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Revoke ALL refresh tokens for the authenticated user (logout all devices).
    Requires a valid access token.
    """
    count = await revoke_all_user_refresh_tokens(current_user.id, db)
    await db.commit()
    logger.info("Revoked %d refresh tokens for user %s", count, current_user.id)


@router.get("/me", response_model=UserProfile, summary="Current user profile")
async def me(
    current_user: User = Depends(get_current_user),
) -> UserProfile:
    """Return the authenticated user's profile. Never returns password hash."""
    return UserProfile(
        user_id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        is_active=current_user.is_active,
    )
