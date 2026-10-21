"""Startup validation helpers (kept import-light so they are easy to unit test)."""
from __future__ import annotations

MIN_SECRET_LENGTH = 32

# Case-insensitive fragments that mark a value as a template/placeholder rather
# than a generated secret.  Real secrets come from ``secrets.token_hex(32)``
# (hex digits only), which can never contain any of these.
PLACEHOLDER_FRAGMENTS = (
    "changeme", "change-me", "change_me", "replace", "placeholder", "insecure",
    "your-secret", "your_secret", "yoursecret", "generate-a", "dev-secret",
)


def secret_key_problem(value: str | None) -> str | None:
    """Return a reason the SECRET_KEY must be refused, or None if it is acceptable."""
    v = (value or "").strip()
    if not v:
        return "empty"
    if len(v) < MIN_SECRET_LENGTH:
        return "too short"
    lowered = v.lower()
    for frag in PLACEHOLDER_FRAGMENTS:
        if frag in lowered:
            return f"contains placeholder text '{frag}'"
    if len(set(v)) < 8:
        return "too little variety"
    return None
