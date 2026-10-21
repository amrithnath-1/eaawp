"""backend/.env.example must document every security-relevant setting and ship no secrets."""
from __future__ import annotations

import pathlib
import re

from app.config import Settings

EXAMPLE = (pathlib.Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
DOCUMENTED = {m.group(1).upper() for m in re.finditer(r"^#?\s*([A-Za-z_][A-Za-z0-9_]*)=", EXAMPLE, re.M)}

REQUIRED_DOCS = [
    "SECRET_KEY", "ENCRYPTION_KEY", "ALGORITHM", "JWT_ISSUER", "JWT_AUDIENCE", "TRUSTED_PROXY_COUNT",
    "RATE_LIMIT_ENABLED", "REGISTRATION_ENABLED", "REGISTRATION_RATE_LIMIT", "REGISTRATION_RATE_WINDOW_SECONDS",
    "REGISTRATION_DAILY_CAP", "LOGIN_RATE_LIMIT", "LOGIN_RATE_WINDOW_SECONDS", "LOGIN_MAX_FAILURES",
    "LOGIN_FAILURE_WINDOW_SECONDS", "REFRESH_RATE_LIMIT", "REFRESH_RATE_WINDOW_SECONDS",
    "OAUTH_CALLBACK_RATE_LIMIT", "OAUTH_CALLBACK_RATE_WINDOW_SECONDS", "CORS_ORIGINS", "ENVIRONMENT", "SQL_ECHO",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
]


def test_every_required_setting_is_documented_and_is_a_real_setting():
    fields = {f.upper() for f in Settings.model_fields}
    assert not [n for n in REQUIRED_DOCS if n not in DOCUMENTED], "undocumented in .env.example"
    assert not [n for n in REQUIRED_DOCS if n not in fields], "documented but not a real setting"


def test_every_rate_limit_and_registration_setting_in_config_is_documented():
    fields = [f.upper() for f in Settings.model_fields
              if f.startswith(("rate_limit", "registration_", "login_", "refresh_", "oauth_callback_",
                               "trusted_proxy", "jwt_", "encryption_"))]
    assert fields
    assert not [f for f in fields if f not in DOCUMENTED]


def test_no_credentials_and_no_stale_auth_claims():
    assert "development\" enables X-Tenant-ID" not in EXAMPLE
    assert not re.search(r"enables X-Tenant-ID header fallback", EXAMPLE)
    for key in ("SECRET_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        m = re.search(rf"^{key}=(.*)$", EXAMPLE, re.M)
        assert m and m.group(1).strip().strip("\"'") == "", f"{key} must be empty in the example"
