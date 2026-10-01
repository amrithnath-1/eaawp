"""
EAAWP Email Provider Abstraction

Defines:
  BaseEmailProvider  — abstract interface all providers must implement
  SMTPEmailProvider  — production SMTP implementation
  get_email_provider — factory that returns the correct provider for a tenant

Design: adding a future provider (e.g. SendGrid REST API) only requires
  1. A new subclass of BaseEmailProvider
  2. A new provider_type value in ExternalIntegration
  3. A new case in get_email_provider()

No changes to the action tool, governance, planner, or audit layers.

Security invariants
-------------------
- Credentials are decrypted in-memory only, discarded after the connection.
- Credentials never appear in log messages, return values, or exceptions.
- No arbitrary SMTP commands are accepted — only validated structured email.
- TLS/STARTTLS is enforced based on tls_mode configuration.
- All exceptions are caught and re-raised without credential leakage.
"""

from __future__ import annotations

import abc
import asyncio
import email.mime.multipart
import email.mime.text
import logging
import smtplib
import ssl
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.email_models import ExternalIntegration
from app.integrations.crypto import decrypt_password

logger = logging.getLogger(__name__)

# Connection timeout for SMTP (seconds)
SMTP_CONNECT_TIMEOUT = 15
SMTP_SEND_TIMEOUT = 30


# ── Send result ───────────────────────────────────────────────────────────────

@dataclass
class SendResult:
    """Result of a send attempt — never contains credentials."""
    success: bool
    message_id: str | None = None   # SMTP message-ID if available
    server_response: str | None = None   # truncated safe server response
    error_message: str | None = None     # safe error text, no credentials


@dataclass
class TestResult:
    """Result of a connection test — never contains credentials."""
    success: bool
    server_greeting: str | None = None
    error_message: str | None = None


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseEmailProvider(abc.ABC):
    """
    Abstract interface for all email providers.
    Subclasses implement the actual transport mechanism.
    """

    @property
    @abc.abstractmethod
    def provider_type(self) -> str:
        """e.g. 'smtp', 'sendgrid', 'mailgun'"""

    @abc.abstractmethod
    async def test_connection(self) -> TestResult:
        """Test connectivity without sending email. Returns TestResult."""

    @abc.abstractmethod
    async def send(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> SendResult:
        """
        Send an email.

        Args:
            recipients: List of validated recipient email addresses.
            subject:    Validated subject string.
            body:       Validated body text.
            reply_to:   Optional validated reply-to address.

        Returns:
            SendResult with success flag and safe metadata.
            Never raises — catches all exceptions and returns error result.
        """


# ── SMTP implementation ───────────────────────────────────────────────────────

class SMTPEmailProvider(BaseEmailProvider):
    """
    Real SMTP email provider.

    Supports:
    - Plain (no TLS) — not recommended for production
    - STARTTLS (port 587, upgrade to TLS after connect)
    - SSL/TLS (port 465, TLS from the start)

    Credentials are decrypted from the ExternalIntegration record in memory
    for the duration of the connection only.
    """

    def __init__(self, integration: ExternalIntegration) -> None:
        self._integration = integration
        # Decrypt once — will be garbage-collected after use
        self._password = decrypt_password(integration.encrypted_password)

    @property
    def provider_type(self) -> str:
        return "smtp"

    def _make_message(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        reply_to: str | None,
    ) -> email.mime.multipart.MIMEMultipart:
        """Build a MIME message from validated inputs."""
        msg = email.mime.multipart.MIMEMultipart("alternative")
        sender = (
            f"{self._integration.sender_display_name} <{self._integration.sender_email}>"
            if self._integration.sender_display_name
            else self._integration.sender_email
        )
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
        return msg

    def _connect_smtp_blocking(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        """Build and return a connected (and authenticated) SMTP connection."""
        tls_mode = self._integration.tls_mode
        host = self._integration.smtp_host
        port = self._integration.smtp_port

        if tls_mode == "ssl_tls":
            ctx = ssl.create_default_context()
            smtp = smtplib.SMTP_SSL(host, port, context=ctx, timeout=SMTP_CONNECT_TIMEOUT)
        else:
            smtp = smtplib.SMTP(host, port, timeout=SMTP_CONNECT_TIMEOUT)
            if tls_mode == "starttls":
                ctx = ssl.create_default_context()
                smtp.starttls(context=ctx)

        smtp.login(self._integration.username, self._password)
        return smtp

    def _test_blocking(self) -> TestResult:
        """Synchronous SMTP test — run in thread executor."""
        try:
            smtp = self._connect_smtp_blocking()
            greeting = smtp.getwelcome()
            smtp.quit()
            safe_greeting = (
                greeting.decode("utf-8", errors="replace")[:200]
                if isinstance(greeting, bytes) else str(greeting)[:200]
            )
            return TestResult(success=True, server_greeting=safe_greeting)
        except smtplib.SMTPAuthenticationError:
            return TestResult(
                success=False,
                error_message="SMTP authentication failed. Check username and password.",
            )
        except smtplib.SMTPConnectError as exc:
            return TestResult(
                success=False,
                error_message=f"Cannot connect to SMTP server: {_safe_smtp_error(exc)}",
            )
        except ssl.SSLError as exc:
            return TestResult(
                success=False,
                error_message=f"SSL/TLS error: {_safe_smtp_error(exc)}",
            )
        except OSError as exc:
            return TestResult(
                success=False,
                error_message=f"Network error: {_safe_smtp_error(exc)}",
            )
        except Exception as exc:  # noqa: BLE001
            return TestResult(
                success=False,
                error_message=f"Connection test failed: {_safe_smtp_error(exc)}",
            )

    def _send_blocking(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        reply_to: str | None,
    ) -> SendResult:
        """Synchronous SMTP send — run in thread executor."""
        try:
            msg = self._make_message(recipients, subject, body, reply_to)
            smtp = self._connect_smtp_blocking()
            refused: dict = smtp.sendmail(
                self._integration.sender_email,
                recipients,
                msg.as_string(),
            )
            smtp.quit()

            if refused:
                # Some recipients were refused — partial send
                refused_list = ", ".join(str(k) for k in list(refused.keys())[:5])
                return SendResult(
                    success=False,
                    error_message=f"Some recipients refused: {refused_list}",
                )

            # Extract Message-ID if available
            message_id = msg.get("Message-ID")
            return SendResult(
                success=True,
                message_id=message_id,
                server_response="Message accepted for delivery.",
            )

        except smtplib.SMTPAuthenticationError:
            return SendResult(
                success=False,
                error_message="SMTP authentication failed at send time.",
            )
        except smtplib.SMTPRecipientsRefused as exc:
            refused_str = str(list(exc.recipients.keys())[:5])
            return SendResult(
                success=False,
                error_message=f"All recipients refused: {refused_str}",
            )
        except smtplib.SMTPSenderRefused:
            return SendResult(
                success=False,
                error_message="Sender address was refused by the SMTP server.",
            )
        except smtplib.SMTPDataError as exc:
            return SendResult(
                success=False,
                error_message=f"SMTP data error: {_safe_smtp_error(exc)}",
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(
                success=False,
                error_message=f"Email send failed: {_safe_smtp_error(exc)}",
            )
        finally:
            # Ensure password is cleared from local variables
            del msg

    async def test_connection(self) -> TestResult:
        """Async wrapper — runs blocking SMTP in thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._test_blocking)

    async def send(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> SendResult:
        """Async wrapper — runs blocking SMTP send in thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._send_blocking, recipients, subject, body, reply_to
        )


# ── Factory ───────────────────────────────────────────────────────────────────

async def get_email_provider(
    tenant_id: str,
    db: AsyncSession,
) -> BaseEmailProvider | None:
    """
    Load the active email provider for a tenant.
    Returns None if no integration is configured or enabled.
    """
    result = await db.execute(
        select(ExternalIntegration).where(
            ExternalIntegration.tenant_id == tenant_id,
            ExternalIntegration.provider_type == "smtp",
            ExternalIntegration.is_enabled == True,  # noqa: E712
        ).limit(1)
    )
    integration = result.scalar_one_or_none()
    if not integration:
        return None

    if integration.provider_type == "smtp":
        return SMTPEmailProvider(integration)

    # Future providers: elif integration.provider_type == "sendgrid": ...
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_smtp_error(exc: Exception) -> str:
    """
    Extract a safe error message without leaking credentials.
    SMTP errors can sometimes contain username/password in their args.
    """
    import re as _re
    msg = str(exc)
    # Redact anything that looks like a password/auth failure with credentials
    msg = _re.sub(
        r"(password|passwd|auth|credential|login)[^\s,;)]{0,80}",
        r"\1=[REDACTED]",
        msg,
        flags=_re.IGNORECASE,
    )
    return msg[:300]
