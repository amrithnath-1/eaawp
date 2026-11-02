"""
Failure diagnosis and the recovery policy shared by every tool call.

classify_error() turns an error text into a category; RECOVERY says what may be done about it. Only idempotent reads
are retried, a bounded number of times with exponential backoff. Authentication, permission, approval and API limits
are never bypassed: those are reported with what is needed.
"""
from __future__ import annotations

import re

CATEGORIES = ("auth", "permission", "rate_limit", "timeout", "unavailable", "not_found", "invalid_args",
              "schema_mismatch", "malformed_output", "policy_blocked", "execution_error")

_RULES: list[tuple[str, re.Pattern]] = [
    ("policy_blocked", re.compile(r"GOVERNANCE REQUIRED|HIGH risk|approval workflow|blocked by policy|not allowed in "
                                  r"the sandbox|sandbox rejected", re.I)),
    ("permission", re.compile(r"PERMISSION DENIED|not been granted|not permitted|forbidden|\b403\b|no access|"
                              r"must grant", re.I)),
    ("auth", re.compile(r"\b401\b|unauthori[sz]ed|invalid[_ ]grant|expired|revoked|reconnect|refresh access token|"
                        r"check the API key", re.I)),
    ("rate_limit", re.compile(r"\b429\b|rate.?limit|quota|too many requests|resource.?exhausted", re.I)),
    ("timeout", re.compile(r"TIMEOUT|timed out|did not respond within|deadline", re.I)),
    ("unavailable", re.compile(r"\b50[0234]\b|unavailable|connection (refused|reset|error)|could not connect|"
                               r"name or service|temporarily|sent an empty answer|sent no answer", re.I)),
    ("not_found", re.compile(r"\b404\b|not found on MCP server|Unknown (capability|tool)|no such tool|"
                             r"is not one of your tools", re.I)),
    ("schema_mismatch", re.compile(r"Unknown parameter|is required|not an allowed field|should be (object|string|"
                                   r"number|integer|array|boolean)|matches none|invalid params|-32602", re.I)),
    ("invalid_args", re.compile(r"VALIDATION ERROR|invalid (date|argument|value)|must be|Invalid JSON|"
                                r"Unsupported (dimension|metric)", re.I)),
    ("malformed_output", re.compile(r"not valid JSON|could not be read|not MCP JSON|malformed|unexpected response", re.I)),
]

TRANSIENT = {"rate_limit", "timeout", "unavailable"}
MAX_RETRIES = 2
BACKOFF_SECONDS = (0.5, 1.5)

NEEDS = {
    "auth": "The connection's sign-in or key is no longer valid: an administrator must reconnect it or replace the key.",
    "permission": "This AI employee has not been granted that tool: an administrator can grant it in Integrations.",
    "rate_limit": "The service's usage limit was reached: wait and try again, or raise the limit with the provider.",
    "policy_blocked": "Company rules do not allow this to run automatically: it needs approval or is not allowed.",
    "not_found": "The tool or address no longer exists on the server: refresh the tool list (TEST NOW).",
}


def classify_error(text: str) -> str | None:
    """Category of a failed tool result, or None when the result is not a failure."""
    t = (text or "").strip()
    if not t:
        return "malformed_output"
    for cat, rx in _RULES:
        if rx.search(t[:2000]):
            return cat
    return "execution_error"


def retryable(category: str | None, *, idempotent: bool) -> bool:
    """Only idempotent (read / compute) calls are retried, and only for transient failures."""
    return idempotent and category in TRANSIENT


def advice(category: str | None) -> str:
    return NEEDS.get(category or "", "")
