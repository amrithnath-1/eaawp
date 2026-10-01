"""
EAAWP Dynamic Integration Framework — Generic Provider Abstraction

This is the foundation of the Phase 2 Integration Framework.

Architecture
────────────
User
 ↓
EAAWP
 ↓
IntegrationManager          (app/integrations/manager.py)
 ↓
IntegrationRegistry         (app/integrations/registry.py)
 ↓
IntegrationProvider (ABC)   ← THIS FILE
 ↓
External System

Design principles
─────────────────
1. Every external system — PostgreSQL, Google Analytics, GitHub, a custom REST
   API — is a provider with a known type string ("postgresql", "google_analytics",
   "github", etc.).

2. A provider defines its *capabilities*: the discrete operations it can perform
   (e.g. "query_table", "get_repo_info", "list_issues").

3. Credential handling is delegated entirely to the manager / credential vault.
   Provider implementations NEVER receive raw credentials in their constructor —
   they receive a decrypted, in-memory credentials dict at call time only.

4. Providers are stateless singletons registered by type string.  The same
   provider instance handles all tenants for that provider type.

5. Capability discovery is deterministic: providers declare their capabilities
   at registration time.  Dynamic discovery (e.g. reading a database schema)
   is a separate operation that enriches the stored Integration record.

6. Future providers (Anthropic, Google Search Console, MCP servers, etc.) are
   added by:
       a. Creating a subclass of IntegrationProvider
       b. Calling registry.register("new_type", MyProvider())
   No other code changes are required.

Security invariants
───────────────────
- credentials dict passed to test/execute is NEVER stored in provider state.
- error messages must not contain credential values (use _safe_error helpers).
- Provider.execute() must validate all input parameters before use.
- Providers may not make tool calls, execute arbitrary code, or spawn
  subprocesses beyond their declared, scoped operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── SSRF protection ───────────────────────────────────────────────────────────

def validate_outbound_host(hostname: str) -> None:
    """
    Raise ValueError if *hostname* resolves to a private, loopback, link-local,
    multicast, or otherwise non-public address.

    Call this before making any outbound network connection to a
    customer-supplied host (database, MCP server, webhook, etc.) to
    prevent Server-Side Request Forgery (SSRF) attacks.

    Uses socket.getaddrinfo so both IPv4 and IPv6 are checked.
    Blocks DNS resolution failures — if the name cannot be resolved
    we refuse the connection rather than allow a potentially dangerous address.
    """
    import ipaddress
    import socket

    if not hostname:
        raise ValueError("Hostname must not be empty.")

    hostname_lower = hostname.strip().lower()

    _BLOCKED_LITERAL_HOSTS = {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "169.254.169.254",
        "::1",
        "0.0.0.0",
    }
    if hostname_lower in _BLOCKED_LITERAL_HOSTS:
        raise ValueError(
            f"Outbound connection to '{hostname}' is not permitted: "
            "internal/metadata hostnames are blocked."
        )
    if hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise ValueError(
            f"Outbound connection to '{hostname}' is not permitted: "
            ".local and .internal domains are blocked."
        )

    try:
        addr_info = socket.getaddrinfo(hostname_lower, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(
            f"Outbound connection to '{hostname}' is not permitted: "
            "hostname could not be resolved."
        )

    for info in addr_info:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"Outbound connection to '{hostname}' resolves to a "
                f"non-public address ({ip_str}) and is not permitted."
            )


# ── Capability category ───────────────────────────────────────────────────────

class CapabilityCategory(str, Enum):
    """Broad category for a capability — used for governance / display grouping."""
    READ      = "read"       # non-mutating queries / data retrieval
    WRITE     = "write"      # creates or modifies records
    PUBLISH   = "publish"    # external-facing side effects (post, send, deploy)
    ADMIN     = "admin"      # account/config management
    ANALYTICS = "analytics"  # reporting and metrics
    WEBHOOK   = "webhook"    # receives or registers webhooks


# ── Risk level ────────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    """
    Governance risk classification for a capability.
    The Integration Manager uses this to determine whether human approval
    is required before a capability can be invoked.
    """
    LOW    = "low"     # read-only, no external side effect
    MEDIUM = "medium"  # creates internal records, reversible
    HIGH   = "high"    # external side effects, hard to undo (send email, publish post)


# ── Provider capability ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderCapability:
    """
    Describes a single discrete operation a provider can perform.

    Capabilities are declared statically by the provider — they do not change
    at runtime based on credentials.  Dynamic information (e.g. which tables
    exist in a database) is represented as the result of executing the
    "discover_schema" capability, not as additional capability objects.

    Fields
    ──────
    key          Unique identifier within this provider.  Snake_case.
                 e.g. "query_table", "list_repositories", "get_analytics"

    display_name Human-readable name for admin UI display.

    description  What the capability does and what input it expects.

    category     Broad governance category (read/write/publish/admin/analytics).

    risk_level   Governance risk; HIGH capabilities always require approval.

    requires_schema_entity  True when the capability operates on a specific
                 discovered entity (e.g. a database table).  The permission
                 layer uses this to enforce per-entity access control.

    input_schema JSON-Schema-like dict describing expected parameters.
                 Used for UI form generation and input validation.
                 None = no structured parameters expected.
    """
    key: str
    display_name: str
    description: str
    category: CapabilityCategory
    risk_level: RiskLevel
    requires_schema_entity: bool = False
    input_schema: dict[str, Any] | None = None


# ── Connection / test results ─────────────────────────────────────────────────

@dataclass
class ConnectionTestResult:
    """
    Result of testing whether a provider can connect using supplied credentials.

    Never stored in full — only `success`, `error_message`, and `account_info`
    (safe metadata, no credentials) are persisted.

    account_info  Safe metadata about the connected account: account name,
                  user email, plan level, version, etc.  Must never contain
                  credentials or secrets.
    """
    success: bool
    account_info: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None   # sanitised — no credentials


@dataclass
class CapabilityResult:
    """
    Result of executing a provider capability.

    data         Structured result payload.  Must not contain credentials,
                 connection strings, or internal infrastructure details.
                 The caller (Integration Manager) is responsible for
                 formatting this for LLM context or API responses.

    row_count    Populated for query/list capabilities.
    truncated    True when results were capped at a limit.
    source_label Human-readable citation for audit records and LLM context.
    error        If not None, the operation failed with this message.
    """
    data: list[dict[str, Any]] | dict[str, Any] | str = field(default_factory=dict)
    row_count: int = 0
    truncated: bool = False
    source_label: str = ""
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None


# ── Abstract provider ─────────────────────────────────────────────────────────

class IntegrationProvider(ABC):
    """
    Abstract base class for all EAAWP Integration Framework providers.

    Subclasses represent a specific *type* of external system
    (e.g. PostgreSQL, Google Analytics, GitHub).  They are stateless
    singletons — a single instance serves all tenants.

    Credentials are NEVER stored on the instance.  They are passed as
    a plain dict to `test_connection()` and `execute()` for the duration
    of that call only.  The caller is responsible for decrypting them
    from the credential vault immediately before the call and discarding
    them immediately after.

    Implementing a new provider
    ──────────────────────────
    1. Subclass IntegrationProvider.
    2. Implement all abstract methods.
    3. Declare capabilities via `get_capabilities()`.
    4. Register: registry.register("my_type", MyProvider())

    See app/integrations/providers/ for examples.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """
        Unique string key for this provider type.
        Matches the `provider_type` column in the Integration ORM model.
        e.g. "postgresql", "google_analytics", "github", "smtp"
        """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for admin UI, e.g. "PostgreSQL Database"."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what this provider connects to."""

    @property
    def icon_hint(self) -> str:
        """
        Optional icon name hint for the frontend (e.g. "database", "github").
        Override to provide a specific icon.  Defaults to "plug".
        """
        return "plug"

    # ── Capabilities ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_capabilities(self) -> list[ProviderCapability]:
        """
        Return the static list of capabilities this provider supports.

        This list is used to:
        - Populate the capability grants UI (which AI employees can do what)
        - Drive input validation in execute()
        - Determine governance risk levels
        - Generate LangChain tool stubs in future phases

        The list must be deterministic — same result on every call.
        """

    def get_capability(self, key: str) -> ProviderCapability | None:
        """Return a specific capability by key, or None if not found."""
        return next((c for c in self.get_capabilities() if c.key == key), None)

    # ── Required credential fields ────────────────────────────────────────────

    @abstractmethod
    def required_credential_fields(self) -> list[str]:
        """
        Return the list of credential field names this provider requires.

        Used by the admin UI to render the correct credential form.
        Used by the credential vault to validate completeness before storing.

        e.g. ["host", "port", "database", "username", "password"]
             ["api_key"]
             ["client_id", "client_secret", "access_token"]

        IMPORTANT: Field names must not suggest their values in error messages.
        """

    def optional_credential_fields(self) -> list[str]:
        """
        Return optional credential field names (defaults to empty list).
        Override to document fields that improve functionality when present.
        """
        return []

    # ── Connectivity ──────────────────────────────────────────────────────────

    @abstractmethod
    async def test_connection(
        self,
        credentials: dict[str, Any],
    ) -> ConnectionTestResult:
        """
        Verify connectivity using the supplied credentials.

        Args:
            credentials: Decrypted credential dict.  Keys match
                         required_credential_fields().  NEVER store this
                         beyond the scope of this method call.

        Returns:
            ConnectionTestResult.  Never raises — catch all exceptions
            internally and return success=False with a safe error message.

        Security:
            - credentials dict must not appear in logs or error messages.
            - Use _sanitise_error() to scrub connection strings from errors.
        """

    # ── Execution ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        """
        Execute a capability.

        Args:
            capability_key: Must match a key in get_capabilities().
            credentials:    Decrypted credentials dict.  Discard immediately.
            parameters:     Caller-supplied, validated parameters for this
                            capability.  Must not contain credentials.

        Returns:
            CapabilityResult with typed data and metadata.

        Raises:
            NotImplementedError: if capability_key is not supported.
            ValueError:          if parameters fail validation.

        Security:
            - Validate all parameters before use.
            - Never reflect credential values in the result.
            - Parameterize all queries — no string interpolation of values.
        """

    # ── Schema / entity discovery ─────────────────────────────────────────────

    async def discover_entities(
        self,
        credentials: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Discover the available entities/resources for this integration.

        For database providers: returns tables/views with column metadata.
        For API providers: returns available endpoints / data sets.
        For providers with no discoverable entities: returns [].

        The result is persisted as SchemaEntity records by the manager.
        Each item must be a safe dict with no credential values.

        Default implementation returns [] (no discovery).
        Override when the provider has discoverable entities.
        """
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sanitise_error(self, msg: str) -> str:
        """
        Remove potentially sensitive content from error messages before
        storing or returning them.  Subclasses may call this in test_connection
        and execute().
        """
        import re
        # Mask password= / password: patterns
        msg = re.sub(r"(?i)(password\s*[=:]\s*)\S+", r"\1[REDACTED]", msg)
        # Mask DSN-style URIs
        msg = re.sub(r"(?i)(://[^:@]+:[^@]+@)", "://[REDACTED]@", msg)
        # Mask api_key / token / secret patterns
        msg = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|secret)[=:\s]+\S+",
            r"\1=[REDACTED]",
            msg,
        )
        return msg[:500]

    def __repr__(self) -> str:
        return f"<IntegrationProvider type={self.provider_type!r}>"
