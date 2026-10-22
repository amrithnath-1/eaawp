"""Helpers for building hostile JWTs in security tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

TEST_SECRET = "security-test-secret-key-0123456789abcdef"


def forge_token(payload_overrides: dict | None = None, *, secret: str = TEST_SECRET,
                algorithm: str = "HS256", drop: tuple[str, ...] = ()) -> str:
    """Build a JWT for negative tests (expired, wrong secret, missing claims...)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "x@example.test",
        "tid": "any",
        "role": "Company Admin",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    payload.update(payload_overrides or {})
    for k in drop:
        payload.pop(k, None)
    return jwt.encode(payload, secret, algorithm=algorithm)
