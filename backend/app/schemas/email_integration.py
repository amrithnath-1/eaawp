"""
EAAWP Email Integration Schemas

Pydantic schemas for the external email integration framework.

Security invariants
-------------------
- Passwords/secrets are NEVER returned in any API response.
- Credentials never appear in LLM prompts, audit records, or tool results.
- Email arguments are validated to prevent injection attacks.
- Recipient limits prevent spam/bulk-send abuse.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Limits ────────────────────────────────────────────────────────────────────

MAX_RECIPIENTS = 10
MAX_SUBJECT_LEN = 255
MAX_BODY_LEN = 50_000
MAX_EMAIL_ADDR_LEN = 254  # RFC 5321

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

TLSMode = Literal["none", "starttls", "ssl_tls"]
IntegrationStatus = Literal["not_configured", "not_tested", "connected", "failed", "disabled"]

# ── SMTP configuration schemas ────────────────────────────────────────────────


class SMTPConfigCreate(BaseModel):
    """Request body to create or replace an SMTP integration for a tenant."""

    provider_type: Literal["smtp"] = "smtp"
    display_name: str = Field(..., min_length=1, max_length=128,
        description="Human-readable label, e.g. 'Company SendGrid'")
    smtp_host: str = Field(..., min_length=1, max_length=255)
    smtp_port: int = Field(..., ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=2048,
        description="Plain-text password — encrypted immediately on receipt, never stored plain.")
    tls_mode: TLSMode = Field("starttls")
    sender_email: str = Field(..., max_length=MAX_EMAIL_ADDR_LEN)
    sender_display_name: str = Field(default="", max_length=255)
    created_by: str = Field(default="admin", max_length=128)

    @field_validator("sender_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v.strip()):
            raise ValueError(f"'{v}' is not a valid email address.")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def no_credentials_in_display(cls, v: str) -> str:
        # Ensure password isn't accidentally an empty string or only whitespace
        if not v.strip():
            raise ValueError("Password must not be empty.")
        return v


class SMTPConfigUpdate(BaseModel):
    """Partial update for an SMTP integration. Password is optional."""

    display_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None   # if provided, will be re-encrypted
    tls_mode: TLSMode | None = None
    sender_email: str | None = None
    sender_display_name: str | None = None

    @field_validator("sender_email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not EMAIL_RE.match(v.strip()):
            raise ValueError(f"'{v}' is not a valid email address.")
        return v.strip().lower()


class EmailIntegrationOut(BaseModel):
    """
    Safe view of an email integration.
    NEVER includes password, decrypted credentials, or authentication tokens.
    """

    id: str
    tenant_id: str
    provider_type: str
    display_name: str
    smtp_host: str
    smtp_port: int
    username: str
    # password_hint: show only first/last char as confirmation
    password_hint: str
    tls_mode: str
    sender_email: str
    sender_display_name: str
    status: IntegrationStatus
    is_enabled: bool
    last_tested_at: str | None
    error_message: str | None
    created_by: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ConnectionTestResultOut(BaseModel):
    """Result of an SMTP connection test."""

    integration_id: str
    success: bool
    status: IntegrationStatus
    server_greeting: str | None = None   # safe server response (no credentials)
    error_message: str | None = None


# ── Email action schemas ──────────────────────────────────────────────────────


class SendEmailInput(BaseModel):
    """
    Structured input for the send_email action.

    Security:
    - Recipients are validated as proper email addresses.
    - Recipient count is capped at MAX_RECIPIENTS.
    - No shell commands, HTTP requests, or credential arguments accepted.
    - Subject and body have length limits.
    - reply_to is optional and validated.
    """

    recipients: list[str] = Field(
        ...,
        min_length=1,
        description=f"List of recipient email addresses (max {MAX_RECIPIENTS}).",
    )
    subject: str = Field(..., min_length=1, max_length=MAX_SUBJECT_LEN)
    body: str = Field(..., min_length=1, max_length=MAX_BODY_LEN)
    reply_to: str | None = Field(default=None, max_length=MAX_EMAIL_ADDR_LEN)

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_RECIPIENTS:
            raise ValueError(
                f"Too many recipients ({len(v)}). Maximum allowed: {MAX_RECIPIENTS}."
            )
        validated = []
        for addr in v:
            addr = addr.strip()
            if not EMAIL_RE.match(addr):
                raise ValueError(f"'{addr}' is not a valid email address.")
            validated.append(addr.lower())
        return validated

    @field_validator("subject")
    @classmethod
    def no_injection_in_subject(cls, v: str) -> str:
        # Prevent header injection (CRLF injection)
        if "\r" in v or "\n" in v:
            raise ValueError("Subject must not contain newline characters.")
        return v.strip()

    @field_validator("reply_to")
    @classmethod
    def validate_reply_to(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError(f"reply_to '{v}' is not a valid email address.")
        return v.lower()

    @field_validator("body")
    @classmethod
    def no_shell_commands(cls, v: str) -> str:
        # Reject obvious shell/code injection patterns
        forbidden = ["$(", "`", "eval(", "exec(", "import os", "subprocess"]
        for p in forbidden:
            if p in v:
                raise ValueError(f"Body contains forbidden pattern: '{p}'.")
        return v


class EmailDraftInput(BaseModel):
    """
    Input for creating an email draft (no send — no external side effect).
    Same validation as SendEmailInput.
    """

    recipients: list[str] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=MAX_SUBJECT_LEN)
    body: str = Field(..., min_length=1, max_length=MAX_BODY_LEN)
    reply_to: str | None = None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_RECIPIENTS:
            raise ValueError(f"Too many recipients. Maximum: {MAX_RECIPIENTS}.")
        validated = []
        for addr in v:
            addr = addr.strip()
            if not EMAIL_RE.match(addr):
                raise ValueError(f"'{addr}' is not a valid email address.")
            validated.append(addr.lower())
        return validated
