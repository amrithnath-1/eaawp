"""
EAAWP Authentication & Tenant Resolution

Security model
──────────────
- Passwords hashed with bcrypt via passlib (never stored in plaintext).
- Issued JWT tokens signed with HS256 using settings.secret_key.
- Every access token carries:
    sub   = user.id
    email = user.email
    tid   = user.tenant_id   (company.id)
    role  = user.role
- The backend derives tenant_id FROM the verified JWT — it never trusts a
  tenant_id supplied in a request header or body.
- Refresh tokens are now DB-persisted (hashed SHA-256) with revocation support.
  On logout: call revoke_refresh_token(jti, db).
  On logout-all: call revoke_all_user_refresh_tokens(user_id, db).

FastAPI dependency chain
────────────────────────
  get_current_user(token) → User
  get_current_tenant_id(token) → str
  require_admin(user)    → User (raises 403 if not admin)

The X-Tenant-ID header is NOT an identity.  It is ignored by every
dependency in this module: tenant_id always comes from the user record
that the verified JWT points to.  A missing, malformed, expired or
wrongly-typed token is rejected with 401 — there is no unauthenticated
fallback.

Never log token values, passwords, or secrets.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt as _bcrypt_lib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt.  Never store the return value in logs."""
    return _bcrypt_lib.hashpw(plain.encode("utf-8"), _bcrypt_lib.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time password verification."""
    try:
        return _bcrypt_lib.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

_ACCESS_TYPE = "access"
_REFRESH_TYPE = "refresh"


def _registered_claims() -> dict[str, Any]:
    """Issuer / audience claims, present only when configured."""
    claims: dict[str, Any] = {}
    if settings.jwt_issuer:
        claims["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        claims["aud"] = settings.jwt_audience
    return claims


def create_access_token(
    user_id: str,
    email: str,
    tenant_id: str,
    role: str,
) -> str:
    """Create a signed JWT access token.  Never log the return value."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "tid": tenant_id,
        "role": role,
        "type": _ACCESS_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        **_registered_claims(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    """Create a long-lived refresh token JWT.  Never log the return value.
    The jti (JWT ID) is a random UUID used to look up the DB record.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=settings.refresh_token_expire_days)
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "tid": tenant_id,
        "jti": jti,
        "type": _REFRESH_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        **_registered_claims(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hash of the raw JWT string for DB storage.  One-way."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def persist_refresh_token(
    raw_token: str,
    user_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """
    Store a hashed refresh token in the DB.
    Called immediately after issuing a new refresh token.
    The raw token is hashed — never stored.
    """
    from app.db.models import RefreshToken
    payload = _decode_token(raw_token, _REFRESH_TYPE)
    jti = payload.get("jti", str(uuid.uuid4()))
    exp_ts = payload.get("exp", 0)
    expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
    token_hash = hash_refresh_token(raw_token)

    record = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=token_hash,
        jti=jti,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(record)
    await db.flush()  # caller commits


async def validate_refresh_token_db(
    raw_token: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Validate a refresh token against the DB.
    Returns the decoded payload if valid.
    Raises HTTP 401 if:
    - Token is not a valid JWT
    - Token is expired
    - Token has been revoked
    - Token is not found in DB (was never issued by this server)
    """
    from app.db.models import RefreshToken
    # First validate JWT signature and expiry
    payload = _decode_token(raw_token, _REFRESH_TYPE)
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Invalid refresh token: missing jti")

    # Look up DB record by jti
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=401, detail="Refresh token not found")
    if record.revoked:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    if record.user_id != payload.get("sub"):
        # The signed subject must be the user the record was issued to.
        raise HTTPException(status_code=401, detail="Refresh token not found")
    now = datetime.now(timezone.utc)
    if as_utc(record.expires_at) < now:
        raise HTTPException(status_code=401, detail="Refresh token expired")

    return payload


async def revoke_refresh_token(jti: str, db: AsyncSession) -> bool:
    """
    Mark a refresh token as revoked by its jti.
    Returns True if found and revoked, False if not found.
    """
    from app.db.models import RefreshToken
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    record = result.scalar_one_or_none()
    if record is None:
        return False
    record.revoked = True
    record.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def revoke_all_user_refresh_tokens(user_id: str, db: AsyncSession) -> int:
    """
    Revoke all active refresh tokens for a user (logout all devices).
    Returns the count of revoked tokens.
    """
    from app.db.models import RefreshToken
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    records = result.scalars().all()
    for r in records:
        r.revoked = True
        r.revoked_at = now
    await db.flush()
    return len(records)


def _decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.

    Raises HTTP 401 on any failure — never reveals why the token is invalid
    beyond a generic message (prevents oracle attacks).
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # Tokens without an expiry or subject are never valid.  When an issuer or
    # audience is configured it is REQUIRED and must match.
    options: dict[str, Any] = {"require_exp": True, "require_sub": True}
    decode_kwargs: dict[str, Any] = {}
    if settings.jwt_issuer:
        options["require_iss"] = True
        decode_kwargs["issuer"] = settings.jwt_issuer
    if settings.jwt_audience:
        options["require_aud"] = True
        decode_kwargs["audience"] = settings.jwt_audience
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options=options,
            **decode_kwargs,
        )
    except JWTError:
        raise credentials_exc

    if payload.get("type") != expected_type:
        raise credentials_exc

    return payload


def as_utc(value: datetime) -> datetime:
    """Treat a naive datetime (SQLite returns these) as UTC; leave aware ones alone."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the authenticated User from a JWT Bearer token.

    Always requires a valid signed JWT — no header-based fallback.
    Use POST /api/v1/auth/token to obtain a token before calling
    any authenticated endpoint.
    """
    if token:
        payload = _decode_token(token, _ACCESS_TYPE)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token subject")
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        return user

    # NOTE: The development-mode X-Tenant-ID fallback that previously granted
    # synthetic Admin access has been intentionally removed.  Every request to
    # an authenticated endpoint must carry a valid Bearer JWT — regardless of
    # the ENVIRONMENT setting.  Use POST /api/v1/auth/token to obtain a token.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_tenant_id(
    user: User = Depends(get_current_user),
) -> str:
    """Return the tenant_id derived from the authenticated user.
    This is the correct way for ALL routers to obtain tenant_id — never
    trust a request parameter or header directly."""
    return user.tenant_id


_ADMIN_ROLES = frozenset({"admin", "superadmin", "company admin", "ai administrator"})


def is_admin_user(user: User) -> bool:
    return (user.role or "").lower() in _ADMIN_ROLES


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Raise 403 if the authenticated user is not an admin."""
    if not is_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# ── Username/password verification (for /auth/token) ─────────────────────────

async def authenticate_user(
    email: str,
    password: str,
    tenant_id: str,
    db: AsyncSession,
) -> User | None:
    """
    Verify email + password for a user within a tenant.

    Returns the User on success, None on failure.
    Never reveals whether the email exists (timing-safe comparison).
    """
    result = await db.execute(
        select(User).where(
            User.email == email,
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        # Run bcrypt anyway to prevent timing oracle attacks
        _bcrypt_lib.checkpw(b"dummy", _bcrypt_lib.hashpw(b"dummy", _bcrypt_lib.gensalt()))
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
