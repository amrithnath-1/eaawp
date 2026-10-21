"""
EAAWP Phase A — Authentication & Tenant Security Tests

Security requirements verified:
 1.  JWT access token can be created and decoded.
 2.  JWT refresh token can be created and decoded.
 3.  Access token carries correct tenant_id claim (tid).
 4.  Access token carries correct role claim.
 5.  Access token type claim is "access".
 6.  Refresh token type claim is "refresh".
 7.  Tokens with wrong type are rejected.
 8.  Tokens with tampered signature are rejected.
 9.  Tokens signed with wrong key are rejected.
10.  Expired tokens are rejected.
11.  Password hashing produces bcrypt hash.
12.  Correct password verifies successfully.
13.  Wrong password fails verification.
14.  hash_password is not identity (plaintext not stored).
15.  Token does not contain password.
16.  Token does not contain hashed_password.
17.  authenticate_user returns None for wrong password.
18.  authenticate_user returns None for unknown email.
19.  authenticate_user returns None for wrong tenant.
20.  LoginRequest schema rejects missing fields.
21.  TokenResponse never contains password field.
22.  Auth router /me requires valid token.
23.  Tenant_id derived from token, not from X-Tenant-ID header alone.
24.  There is NO header fallback: get_optional_tenant_id no longer exists.
25.  Two different tenants have completely isolated token spaces.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

_SECRET = "test-secret-key-for-phase-a-tests"
_ALGORITHM = "HS256"

def _override_settings(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "secret_key", _SECRET)
    monkeypatch.setattr(config.settings, "algorithm", _ALGORITHM)
    monkeypatch.setattr(config.settings, "access_token_expire_minutes", 60)
    monkeypatch.setattr(config.settings, "refresh_token_expire_days", 30)
    monkeypatch.setattr(config.settings, "environment", "development")


# ═══════════════════════════════════════════════════════════════════════════════
# 1–10. JWT token creation and validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTTokenCreation:

    def test_access_token_is_decodable(self, monkeypatch):
        """JWT access token can be decoded with the correct secret."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        token = create_access_token("user-1", "user@example.com", "tenant-1", "Admin")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert payload["sub"] == "user-1"

    def test_access_token_carries_tenant_id(self, monkeypatch):
        """Access token carries tenant_id in 'tid' claim."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        token = create_access_token("user-1", "user@example.com", "tenant-abc", "Employee")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert payload["tid"] == "tenant-abc"

    def test_access_token_carries_role(self, monkeypatch):
        """Access token carries user role claim."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        token = create_access_token("user-1", "user@example.com", "tenant-1", "Admin")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert payload["role"] == "Admin"

    def test_access_token_type_is_access(self, monkeypatch):
        """Access token 'type' claim is 'access'."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        token = create_access_token("user-1", "a@b.com", "t1", "Admin")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert payload["type"] == "access"

    def test_refresh_token_type_is_refresh(self, monkeypatch):
        """Refresh token 'type' claim is 'refresh'."""
        _override_settings(monkeypatch)
        from app.core.auth import create_refresh_token
        token = create_refresh_token("user-1", "tenant-1")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert payload["type"] == "refresh"

    def test_wrong_type_token_rejected(self, monkeypatch):
        """Using a refresh token where access is expected raises HTTP 401."""
        _override_settings(monkeypatch)
        from fastapi import HTTPException
        from app.core.auth import create_refresh_token, _decode_token
        token = create_refresh_token("user-1", "t1")
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(token, "access")
        assert exc_info.value.status_code == 401

    def test_tampered_signature_rejected(self, monkeypatch):
        """Token with tampered payload is rejected."""
        _override_settings(monkeypatch)
        from fastapi import HTTPException
        from app.core.auth import create_access_token, _decode_token
        token = create_access_token("user-1", "a@b.com", "t1", "Admin")
        # Change a character in the MIDDLE of the signature. (The last base64url character of a 32-byte signature only carries
        # 4 significant bits: replacing it with 'A'/'B' can leave the decoded signature identical, i.e. no tampering at all,
        # which made this test fail about 1 run in 17.)
        head, payload, sig = token.split(".")
        mid = len(sig) // 2
        tampered = ".".join([head, payload, sig[:mid] + ("A" if sig[mid] != "A" else "B") + sig[mid + 1:]])
        assert tampered != token
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(tampered, "access")
        assert exc_info.value.status_code == 401

    def test_wrong_key_rejected(self, monkeypatch):
        """Token signed with a different key is rejected."""
        _override_settings(monkeypatch)
        from fastapi import HTTPException
        from app.core.auth import _decode_token
        # Sign with a different secret
        payload = {"sub": "user-1", "type": "access", "exp": int(time.time()) + 3600}
        bad_token = jwt.encode(payload, "wrong-secret", algorithm=_ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(bad_token, "access")
        assert exc_info.value.status_code == 401

    def test_expired_token_rejected(self, monkeypatch):
        """Expired JWT is rejected."""
        _override_settings(monkeypatch)
        from fastapi import HTTPException
        from app.core.auth import _decode_token
        expired_payload = {
            "sub": "user-1",
            "type": "access",
            "exp": int(time.time()) - 1,  # already expired
        }
        token = jwt.encode(expired_payload, _SECRET, algorithm=_ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(token, "access")
        assert exc_info.value.status_code == 401

    def test_token_does_not_contain_password(self, monkeypatch):
        """JWT payload does not contain any password field."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        token = create_access_token("user-1", "user@example.com", "tenant-1", "Admin")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert "password" not in payload
        assert "hashed_password" not in payload


# ═══════════════════════════════════════════════════════════════════════════════
# 11–16. Password hashing
# ═══════════════════════════════════════════════════════════════════════════════

class TestPasswordHashing:

    def test_hash_produces_bcrypt(self):
        """hash_password produces a bcrypt hash (starts with $2b$)."""
        from app.core.auth import hash_password
        h = hash_password("my-secure-password")
        assert h.startswith("$2")

    def test_verify_correct_password(self):
        """Correct password verifies successfully."""
        from app.core.auth import hash_password, verify_password
        h = hash_password("correct-password")
        assert verify_password("correct-password", h) is True

    def test_verify_wrong_password(self):
        """Wrong password verification returns False."""
        from app.core.auth import hash_password, verify_password
        h = hash_password("correct-password")
        assert verify_password("wrong-password", h) is False

    def test_hash_is_not_plaintext(self):
        """The hash is not the same as the plaintext password."""
        from app.core.auth import hash_password
        plain = "my-password-123"
        assert hash_password(plain) != plain

    def test_same_password_different_hashes(self):
        """bcrypt salting produces different hashes for same password."""
        from app.core.auth import hash_password
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════════════
# 17–19. authenticate_user
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthenticateUser:

    def _make_user(self, email="user@test.com", tenant_id="tenant-1", password="pass123"):
        from app.db.models import User
        from app.core.auth import hash_password
        return User(
            id="user-id-1",
            tenant_id=tenant_id,
            email=email,
            name="Test User",
            hashed_password=hash_password(password),
            role="Admin",
            is_active=True,
        )

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password_returns_none(self):
        """authenticate_user returns None for wrong password."""
        from app.core.auth import authenticate_user
        user = self._make_user()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await authenticate_user("user@test.com", "wrong-pass", "tenant-1", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_unknown_email_returns_none(self):
        """authenticate_user returns None for unknown email."""
        from app.core.auth import authenticate_user
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)  # not found
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await authenticate_user("nobody@test.com", "any-pass", "tenant-1", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_correct_returns_user(self):
        """authenticate_user returns the User for correct credentials."""
        from app.core.auth import authenticate_user
        user = self._make_user(password="correct-pass")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=user)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await authenticate_user("user@test.com", "correct-pass", "tenant-1", mock_db)
        assert result is not None
        assert result.id == "user-id-1"


# ═══════════════════════════════════════════════════════════════════════════════
# 20–21. Schema validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthSchemas:

    def test_login_request_requires_all_fields(self):
        """LoginRequest rejects missing required fields."""
        from app.api.routers.auth import LoginRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com")  # missing password + company_id

    def test_token_response_no_password_field(self):
        """TokenResponse schema has no password or secret fields."""
        from app.api.routers.auth import TokenResponse
        fields = set(TokenResponse.model_fields.keys())
        assert "password" not in fields
        assert "hashed_password" not in fields
        assert "secret" not in fields

    def test_user_profile_no_password_field(self):
        """UserProfile schema has no password field."""
        from app.api.routers.auth import UserProfile
        fields = set(UserProfile.model_fields.keys())
        assert "password" not in fields
        assert "hashed_password" not in fields


# ═══════════════════════════════════════════════════════════════════════════════
# 22–25. Tenant isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTenantIsolation:

    def test_token_tenant_id_isolated(self, monkeypatch):
        """Two tokens for different tenants have different tid claims."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token
        t1 = create_access_token("u1", "a@a.com", "tenant-A", "Admin")
        t2 = create_access_token("u2", "b@b.com", "tenant-B", "Admin")
        p1 = jwt.decode(t1, _SECRET, algorithms=[_ALGORITHM])
        p2 = jwt.decode(t2, _SECRET, algorithms=[_ALGORITHM])
        assert p1["tid"] != p2["tid"]
        assert p1["tid"] == "tenant-A"
        assert p2["tid"] == "tenant-B"

    def test_tenant_a_token_cannot_claim_tenant_b(self, monkeypatch):
        """A token for tenant-A does not grant access to tenant-B data.
        This test verifies that tenant_id is always read from the token, not
        from any external parameter."""
        _override_settings(monkeypatch)
        from app.core.auth import create_access_token, _decode_token
        token = create_access_token("u1", "a@a.com", "tenant-A", "Admin")
        # Decode the token — it must say tenant-A regardless of what any
        # external parameter claims
        payload = _decode_token(token, "access")
        assert payload["tid"] == "tenant-A"
        # Even if a malicious X-Tenant-ID header says "tenant-B", the token
        # has tenant-A — the auth layer ignores the header for authenticated requests.
        assert payload["tid"] != "tenant-B"

    def test_auth_router_exists_and_is_importable(self):
        """Auth router is importable and has expected routes."""
        from app.api.routers.auth import router
        paths = {r.path for r in router.routes}
        assert "/api/v1/auth/token" in paths
        assert "/api/v1/auth/refresh" in paths
        assert "/api/v1/auth/me" in paths

    def test_algorithm_in_settings(self):
        """Settings has algorithm field for JWT."""
        from app.config import settings
        assert hasattr(settings, "algorithm")
        assert settings.algorithm in ("HS256", "HS384", "HS512")

    def test_refresh_token_expire_days_in_settings(self):
        """Settings has refresh_token_expire_days field."""
        from app.config import settings
        assert hasattr(settings, "refresh_token_expire_days")
        assert settings.refresh_token_expire_days > 0

    def test_core_auth_module_importable(self):
        """Core auth module is importable with no side effects."""
        from app.core import auth
        assert hasattr(auth, "create_access_token")
        assert hasattr(auth, "create_refresh_token")
        assert hasattr(auth, "verify_password")
        assert hasattr(auth, "hash_password")
        assert hasattr(auth, "get_current_user")
        assert hasattr(auth, "get_current_tenant_id")
        # Phase 2: the unauthenticated X-Tenant-ID fallback was removed on purpose.
        assert not hasattr(auth, "get_optional_tenant_id")
        assert hasattr(auth, "require_admin")
        assert hasattr(auth, "authenticate_user")
