"""
EAAWP Phase 3 — Dynamic Capability → Tool Registration

Bridges the Phase 2 Integration Framework to the existing AI execution system.

Architecture
────────────
ProviderCapability (static metadata on a registered provider)
        ↓
DynamicToolDefinition (safe runtime description — NO credentials)
        ↓
build_dynamic_tool_adapter() → LangChain @tool-decorated function
        ↓
DynamicAgentEngine / Planner (per-request tool map)
        ↓
IntegrationManager.execute_capability() — full security pipeline
        ↓
Provider → External System

Key design decisions
────────────────────

1.  NO global registry mutation.
    MASTER_TOOL_REGISTRY is process-global. Injecting tenant-specific tools
    there would cause cross-tenant leakage. Instead, dynamic tools are built
    per-request and passed into the engine/planner as a separate supplementary
    dict (_dynamic_tool_map). The engine/planner check this map AFTER the
    static registry, so static tools always take precedence.

2.  NO arbitrary code generation.
    build_dynamic_tool_adapter() creates a properly typed, pre-validated
    LangChain @tool wrapper around a fixed execution path. The function body
    is constant — only the routing metadata (integration_id, capability_key)
    is parameterised by the DynamicToolDefinition values captured in the closure.
    eval() and exec() are never used.

3.  NO credential exposure.
    The adapter receives JSON tool arguments from the LLM (structured parameters
    only — no credential fields allowed). Credentials are decrypted inside
    IntegrationManager.execute_capability() from the encrypted DB record,
    never passed through tool arguments.

4.  Tenant isolation via ContextVar.
    tenant_id and role_key are injected by the execution router via existing
    ContextVar mechanisms (set_tool_context / _dynamic_tools_ctx). The adapter
    reads them at call time. The LLM cannot override them.

5.  Input validation.
    Every tool call validates arguments against the ProviderCapability's
    declared input_schema. Unknown fields, credential-like fields, and
    oversized payloads are rejected before reaching the provider.

6.  Risk routing.
    LOW/MEDIUM capabilities execute directly (matching the existing pattern
    for read tools). HIGH capabilities raise PermissionError — they must go
    through the existing action governance pipeline first. This is intentional:
    Phase 3 does not bypass ACTION_REGISTRY; it honours it.

7.  Deterministic tool names.
    Tool keys are: integration_<short_id>_<capability_key>
    where short_id is the first 8 hex chars of the integration UUID.
    This is collision-resistant, deterministic, and safe as a function name.

Security invariants
───────────────────
- Tool arguments never contain credentials.
- tenant_id / role_key come from ContextVar, not LLM arguments.
- Invalid or unknown fields are rejected before reaching the provider.
- Credential-looking field names in arguments are rejected.
- Result is bounded (MAX_RESULT_ROWS, MAX_RESULT_CHARS).
- Errors are sanitised before returning to the LLM.
- HIGH risk capabilities are blocked (governance required first).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool as langchain_tool

logger = logging.getLogger(__name__)

# ── Safety limits ─────────────────────────────────────────────────────────────

MAX_RESULT_ROWS: int = 100       # cap rows returned to LLM
MAX_RESULT_CHARS: int = 8_000    # cap total result string length
MAX_PARAM_STRING_LEN: int = 500  # cap any single string parameter value
MAX_LIMIT: int = 200             # cap for query limit parameters
MAX_FILTER_COUNT: int = 10       # cap number of filters
MAX_FIELDS: int = 30             # cap number of requested fields

# Fields that, if present in tool arguments, indicate credential injection attempts
_FORBIDDEN_PARAM_FIELDS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "api_key", "access_token", "refresh_token",
    "private_key", "token", "credential", "credentials", "auth", "authorization",
    "bearer", "client_secret", "connection_string", "dsn", "jdbc",
    "encrypted_credentials",
})

# ── Tool name utilities ────────────────────────────────────────────────────────

def make_tool_key(integration_id: str, capability_key: str) -> str:
    """
    Build a deterministic, safe tool key from an integration ID and capability.

    Format: integration_<8-char-hex-id>_<capability_key>

    The 8-char prefix is enough to identify a specific integration while keeping
    the key short. The capability_key is normalised to snake_case alphanumerics.

    Examples:
        integration_a1b2c3d4_query_entity
        integration_ff003311_discover_schema
    """
    short_id = integration_id.replace("-", "")[:8].lower()
    safe_cap = re.sub(r"[^a-z0-9_]", "_", capability_key.lower())
    return f"integration_{short_id}_{safe_cap}"


def is_dynamic_tool_key(tool_key: str) -> bool:
    """Return True if the key looks like a Phase 3 dynamic tool key."""
    return bool(re.match(r"^integration_[0-9a-f]{8}_[a-z0-9_]+$", tool_key))


# ── DynamicToolDefinition ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class DynamicToolDefinition:
    """
    Safe, credential-free descriptor of one dynamic tool available to a role.

    Created at request time by get_available_tools(). Never stored globally.
    Contains NO credentials, NO encrypted blobs, NO sensitive identifiers
    beyond the integration_id (which is an opaque UUID).

    Fields
    ──────
    tool_key            LangChain tool name (safe, deterministic).
    integration_id      UUID of the Integration record.
    tenant_id           Tenant that owns this integration. Validated at
                        execution time — not trusted from LLM arguments.
    role_key            Role that was granted this capability.
    capability_key      Provider capability identifier (e.g. "query_entity").
    provider_type       Provider type string (e.g. "postgresql").
    integration_name    Human-readable integration display name.
    description         Tool description shown to the LLM.
    risk_level          "low" | "medium" | "high".
    is_read_only        True when category == READ or ANALYTICS.
    input_schema        Provider-declared safe parameter schema.
    is_enabled          Whether the integration is currently connected+enabled.
    """
    tool_key: str
    integration_id: str
    tenant_id: str
    role_key: str
    capability_key: str
    provider_type: str
    integration_name: str
    description: str
    risk_level: str
    is_read_only: bool
    input_schema: dict[str, Any] | None
    is_enabled: bool


# ── Input validation ──────────────────────────────────────────────────────────

def validate_tool_arguments(
    raw_args: dict[str, Any],
    capability_key: str,
    input_schema: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Validate and sanitise tool arguments against the capability's input schema.

    Returns:
        (is_valid, error_message, sanitised_args)

    Security checks performed:
    1. No credential-like field names.
    2. No fields named "tenant_id" or "role_key" (must never come from LLM).
    3. String values truncated to MAX_PARAM_STRING_LEN.
    4. "limit" capped to MAX_LIMIT.
    5. "filters" list capped to MAX_FILTER_COUNT.
    6. "fields" list capped to MAX_FIELDS.
    7. Unknown top-level fields rejected if input_schema declares known fields.

    Does NOT: execute SQL, eval(), exec(), or any code from the arguments.
    """
    if not isinstance(raw_args, dict):
        return False, "Tool arguments must be a JSON object.", {}

    # Guard: credential injection
    for field_name in raw_args:
        if field_name.lower() in _FORBIDDEN_PARAM_FIELDS:
            return (
                False,
                f"Field '{field_name}' is not permitted in tool arguments. "
                "Credentials must never be passed through tool parameters.",
                {},
            )

    # Guard: tenant/role injection
    for protected in ("tenant_id", "role_key", "integration_id"):
        if protected in raw_args:
            return (
                False,
                f"Field '{protected}' cannot be set through tool arguments. "
                "It is determined by the execution context.",
                {},
            )

    sanitised: dict[str, Any] = {}

    for k, v in raw_args.items():
        # Sanitise string values
        if isinstance(v, str):
            if len(v) > MAX_PARAM_STRING_LEN:
                return (
                    False,
                    f"Field '{k}' value exceeds maximum length ({MAX_PARAM_STRING_LEN} chars).",
                    {},
                )
            sanitised[k] = v

        elif k == "limit" and isinstance(v, (int, float)):
            capped = min(int(v), MAX_LIMIT)
            if capped < 1:
                return False, "limit must be at least 1.", {}
            sanitised[k] = capped

        elif k == "filters" and isinstance(v, list):
            if len(v) > MAX_FILTER_COUNT:
                return (
                    False,
                    f"Too many filters: {len(v)} (max {MAX_FILTER_COUNT}).",
                    {},
                )
            sanitised[k] = v

        elif k == "fields" and isinstance(v, list):
            if len(v) > MAX_FIELDS:
                return False, f"Too many fields requested (max {MAX_FIELDS}).", {}
            sanitised[k] = v

        elif isinstance(v, (int, float, bool)):
            sanitised[k] = v

        elif isinstance(v, list):
            sanitised[k] = v

        elif isinstance(v, dict):
            sanitised[k] = v

        else:
            # Reject unknown types
            return (
                False,
                f"Field '{k}' has an unsupported type: {type(v).__name__}.",
                {},
            )

    # If input_schema declares allowed fields, reject unknown top-level keys
    if input_schema and "properties" in input_schema:
        allowed_keys = set(input_schema["properties"].keys())
        unknown = {k for k in sanitised if k not in allowed_keys}
        if unknown:
            return (
                False,
                f"Unknown parameter(s): {sorted(unknown)}. "
                f"Allowed: {sorted(allowed_keys)}.",
                {},
            )

    return True, "", sanitised


# ── Build the LangChain @tool adapter ────────────────────────────────────────

def build_dynamic_tool_adapter(defn: DynamicToolDefinition) -> Any:
    """
    Build a LangChain @tool-decorated function for a DynamicToolDefinition.

    The produced function:
    - Accepts a JSON string of parameters from the LLM.
    - Validates against the capability's input_schema.
    - Reads tenant_id and role_key from ContextVars (never from LLM args).
    - Calls IntegrationManager.execute_capability() via the request DB session.
    - Returns a bounded, sanitised string result.
    - Never exposes credentials or connection details.

    The function body is constant — only the routing metadata (integration_id,
    capability_key, etc.) is parameterised through the closure.

    No eval(), exec(), or code generation from external data is used.
    """
    # Capture everything needed from the definition in the closure
    _integration_id = defn.integration_id
    _capability_key = defn.capability_key
    _risk_level = defn.risk_level
    _integration_name = defn.integration_name
    _input_schema = defn.input_schema
    _tool_key = defn.tool_key

    # Build a safe, truncated description for the LLM
    desc = (
        f"{defn.description} "
        f"[Integration: {defn.integration_name}, "
        f"Provider: {defn.provider_type}, "
        f"Risk: {defn.risk_level.upper()}] "
        "Args: JSON string with structured parameters (no credentials, no SQL)."
    )

    # The tool body is constant; only the closure-captured routing metadata
    # differs per tool.  There is ONE execution path, written as a coroutine, so
    # it runs on the request's own event loop with the request's own DB session.
    # (An earlier sync adapter bridged to the loop through threads; the bridge
    # crashed with an unbound ``loop`` and could never share the async session.)

    def _high_risk_block() -> str:
        return (
            f"[GOVERNANCE REQUIRED] Capability '{_capability_key}' on "
            f"'{_integration_name}' is HIGH risk and cannot be executed "
            "directly. It must go through the human approval workflow."
        )

    def _precheck(params_json: Any) -> tuple[str | None, dict[str, Any], Any, str, str]:
        """Context, risk and argument checks.  Returns (error, args, db, tenant, role)."""
        from app.tools.registry import _db_session_ctx, _role_key_ctx, _tenant_id_ctx

        db = _db_session_ctx.get()
        tenant_id = _tenant_id_ctx.get()
        role_key = _role_key_ctx.get()

        if db is None:
            return (
                f"[ERROR] {_tool_key}: no database session available. "
                "This tool requires an active request context.",
                {}, None, tenant_id, role_key,
            )
        try:
            raw = json.loads(params_json) if isinstance(params_json, str) else params_json
        except json.JSONDecodeError as exc:
            return f"[ERROR] {_tool_key}: invalid JSON parameters — {exc}", {}, db, tenant_id, role_key
        is_valid, err_msg, sanitised = validate_tool_arguments(raw, _capability_key, _input_schema)
        if not is_valid:
            return f"[VALIDATION ERROR] {_tool_key}: {err_msg}", {}, db, tenant_id, role_key
        return None, sanitised, db, tenant_id, role_key

    async def _execute(params_json: str = "{}") -> str:
        """Dynamic integration tool (async path)."""
        if _risk_level == "high":      # first check, before anything is parsed or run
            return _high_risk_block()
        err, sanitised, db, tenant_id, role_key = _precheck(params_json)
        if err:
            return err

        # The manager performs every security check: tenant ownership, connected
        # + enabled, and the role's capability grant.  Credentials are decrypted
        # there and never pass through this function.
        from app.integrations.manager import execute_capability as mgr_execute

        try:
            exec_result = await asyncio.wait_for(
                mgr_execute(
                    integration_id=_integration_id,
                    capability_key=_capability_key,
                    parameters=sanitised,
                    role_key=role_key,
                    tenant_id=tenant_id,
                    db=db,
                ),
                timeout=60,
            )
        except asyncio.TimeoutError:
            await _write_dynamic_tool_audit(
                _integration_id, _capability_key, _tool_key, role_key, tenant_id,
                False, 0, "timed out after 60 s", db,
            )
            return f"[TIMEOUT] {_tool_key}: integration call timed out after 60 s"
        except PermissionError as exc:
            await _write_dynamic_tool_audit(
                _integration_id, _capability_key, _tool_key, role_key, tenant_id,
                False, 0, f"permission denied: {exc}", db,
            )
            return f"[PERMISSION DENIED] {_tool_key}: {exc}"
        except (LookupError, ValueError) as exc:
            await _write_dynamic_tool_audit(
                _integration_id, _capability_key, _tool_key, role_key, tenant_id,
                False, 0, str(exc), db,
            )
            return f"[INTEGRATION ERROR] {_tool_key}: {exc}"

        await _write_dynamic_tool_audit(
            _integration_id, _capability_key, _tool_key, role_key, tenant_id,
            exec_result.success, exec_result.row_count, exec_result.error, db,
        )
        if not exec_result.success:
            return f"[INTEGRATION ERROR] {_tool_key}: {exec_result.error or 'Unknown error'}"
        return _format_result_for_llm(
            exec_result=exec_result,
            tool_key=_tool_key,
            integration_name=_integration_name,
            capability_key=_capability_key,
        )

    def _sync_execute(params_json: str = "{}") -> str:
        """Synchronous entry point (no running event loop only)."""
        if _risk_level == "high":
            return _high_risk_block()
        err, *_ = _precheck(params_json)
        if err:
            return err
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_execute(params_json))
        return (
            f"[ERROR] {_tool_key}: this tool is asynchronous; "
            "call it with ainvoke() from async code."
        )

    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        func=_sync_execute,
        coroutine=_execute,
        name=defn.tool_key,
        description=desc,
    )


# ── Result formatting ─────────────────────────────────────────────────────────

# Count-like metrics that can be added up across rows (users, rates and
# averages cannot, so they are never totalled).
_ADDITIVE_METRICS = ("sessions", "screenPageViews", "eventCount", "conversions", "totalRevenue", "clicks", "impressions")


def _derived_lines(rows: list[Any]) -> list[str]:
    """Deterministic totals and shares so the model never has to do arithmetic."""
    dict_rows = [r for r in rows if isinstance(r, dict)]
    if not dict_rows:
        return []
    out: list[str] = []
    for metric in _ADDITIVE_METRICS:
        try:
            vals = [float(str(r[metric]).replace(",", "")) for r in dict_rows if metric in r]
        except ValueError:
            continue
        if len(vals) != len(dict_rows):
            continue
        total = sum(vals)
        out.append("")
        out.append(f"Total {metric} across the {len(dict_rows)} rows above: {total:,.0f}")
        if total > 0 and len(dict_rows) > 1:
            label_key = next((k for k, v in dict_rows[0].items() if k != metric and not _is_number(v)), None)
            if label_key:
                shares = ", ".join(
                    f"{r.get(label_key)} {v / total * 100:.1f}%" for r, v in zip(dict_rows, vals)
                )
                out.append(f"Share of {metric} by {label_key}: {shares}")
        break  # one worked example metric is enough; the rows carry the rest
    out.extend(_search_derived_lines(dict_rows))
    return out


def _search_derived_lines(dict_rows: list[dict]) -> list[str]:
    """Search Console extras: overall CTR from clicks/impressions, and the dates present."""
    out: list[str] = []
    try:
        clicks = sum(float(str(r["clicks"]).replace(",", "")) for r in dict_rows)
        imps = sum(float(str(r["impressions"]).replace(",", "")) for r in dict_rows)
    except (KeyError, ValueError):
        clicks = imps = -1.0
    if imps > 0 and clicks >= 0:
        out.append(f"Overall CTR across these rows (total clicks / total impressions): {clicks / imps * 100:.2f}%")
    if all("date" in r for r in dict_rows):
        dates = sorted(str(r["date"]) for r in dict_rows)
        out.append(f"Dates with data: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    return out


def _is_redundant_dimensions(key: str, value: Any, row: dict) -> bool:
    """Search Console rows carry both named columns and a raw ``dimensions`` list; show one."""
    if key != "dimensions" or not isinstance(value, list):
        return False
    return not value or all(any(v == o for k, o in row.items() if k != key) for v in value)


def _is_number(v: Any) -> bool:
    try:
        float(str(v).replace(",", ""))
        return True
    except ValueError:
        return False


def _format_result_for_llm(
    exec_result: Any,
    tool_key: str,
    integration_name: str,
    capability_key: str,
) -> str:
    """
    Convert an ExecuteCapabilityResponse to a safe, bounded string for LLM context.

    Limits:
        - MAX_RESULT_ROWS rows included
        - MAX_RESULT_CHARS total characters
    No credentials, connection strings, or internal infrastructure details.
    """
    data = exec_result.data
    source = exec_result.source_label or integration_name

    if isinstance(data, str):
        result_str = data[:MAX_RESULT_CHARS]
        if exec_result.truncated or len(data) > MAX_RESULT_CHARS:
            result_str += "\n[Results truncated]"
        return f"[{tool_key}] Source: {source}\n{result_str}"

    if isinstance(data, list):
        rows = data[:MAX_RESULT_ROWS]
        truncated = exec_result.truncated or len(data) > MAX_RESULT_ROWS

        lines = [
            f"[{tool_key}] Integration: {integration_name}",
            f"Source: {source}",
            f"Capability: {capability_key}",
            f"Rows: {exec_result.row_count}"
            + (" (truncated)" if truncated else ""),
            "",
        ]
        for i, row in enumerate(rows, 1):
            if isinstance(row, dict):
                # Omit any key that looks like it could contain a credential
                safe_row = {
                    k: v for k, v in row.items()
                    if k.lower() not in _FORBIDDEN_PARAM_FIELDS
                    and not _is_redundant_dimensions(k, v, row)
                }
                row_str = " | ".join(f"{k}: {v}" for k, v in safe_row.items())
            else:
                row_str = str(row)
            lines.append(f"  {i}. {row_str}")

        lines.extend(_derived_lines(rows))
        result_str = "\n".join(lines)
        if len(result_str) > MAX_RESULT_CHARS:
            result_str = result_str[:MAX_RESULT_CHARS] + "\n[Result truncated due to size]"
        return result_str

    if isinstance(data, dict):
        # Remove any credential-like keys
        safe = {k: v for k, v in data.items() if k.lower() not in _FORBIDDEN_PARAM_FIELDS}
        result_str = json.dumps(safe, indent=2, default=str)[:MAX_RESULT_CHARS]
        return f"[{tool_key}] Source: {source}\n{result_str}"

    return f"[{tool_key}] Result: {str(data)[:MAX_RESULT_CHARS]}"


# ── Audit writer ──────────────────────────────────────────────────────────────

async def _write_dynamic_tool_audit(
    integration_id: str,
    capability_key: str,
    tool_key: str,
    role_key: str,
    tenant_id: str,
    success: bool,
    row_count: int,
    error: str | None,
    db: Any,
) -> None:
    """
    Write a DynamicToolAuditLog record for this execution (every outcome:
    success, provider error, permission denial, timeout).

    Never raises - an audit failure is logged but must not break the request.
    Stores no credentials, connection strings or row data.
    """
    try:
        from app.db.integration_models import DynamicToolAuditLog

        db.add(DynamicToolAuditLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            integration_id=integration_id,
            role_key=role_key,
            capability_key=capability_key,
            tool_key=tool_key,
            success=success,
            row_count=row_count,
            error_message=(error or "")[:500] if error else None,
        ))
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dynamic tool audit write failed (non-fatal): %s", type(exc).__name__)


# Result prefixes that mean "this call did NOT produce data".  The planner and
# the engine use this single list so a failed call is never presented as data.
TOOL_FAILURE_PREFIXES: tuple[str, ...] = (
    "[TOOL ERROR]", "[ERROR]", "[INTEGRATION ERROR]", "[VALIDATION ERROR]",
    "[GOVERNANCE REQUIRED]", "[PERMISSION DENIED]", "[TIMEOUT]",
)


def is_tool_failure(result: str) -> bool:
    return (result or "").lstrip().startswith(TOOL_FAILURE_PREFIXES)


# ── Tool availability query ────────────────────────────────────────────────────

async def get_available_tools(
    tenant_id: str,
    role_key: str,
    db: Any,
) -> list[DynamicToolDefinition]:
    """
    Return the dynamic tools currently available to a role for a tenant.

    Queries:
    1. All enabled integrations for the tenant.
    2. All active capability grants for (integration, role_key).
    3. Validates each capability still exists in the provider registry.

    Returns a list of DynamicToolDefinitions — safe metadata only, no credentials.

    This is used by:
    - The execution router to build the per-request tool map.
    - The planner to build the authorized tool list.
    - The /tools discovery endpoint.
    """
    from sqlalchemy import select

    from app.db.integration_models import CapabilityGrant, Integration
    from app.integrations.integration_registry import integration_registry

    # Fetch all connected, enabled integrations for this tenant
    int_result = await db.execute(
        select(Integration).where(
            Integration.tenant_id == tenant_id,
            Integration.status == "connected",
            Integration.is_enabled == True,  # noqa: E712
        )
    )
    integrations: dict[str, Integration] = {
        row.id: row for row in int_result.scalars().all()
    }

    if not integrations:
        return []

    # Fetch all active grants for this role across those integrations
    grant_result = await db.execute(
        select(CapabilityGrant).where(
            CapabilityGrant.tenant_id == tenant_id,
            CapabilityGrant.role_key == role_key,
            CapabilityGrant.is_granted == True,  # noqa: E712
            CapabilityGrant.integration_id.in_(list(integrations.keys())),
        )
    )
    grants = grant_result.scalars().all()

    tools: list[DynamicToolDefinition] = []
    seen_keys: set[str] = set()

    for grant in grants:
        integration = integrations.get(grant.integration_id)
        if integration is None:
            continue

        provider = integration_registry.get(integration.provider_type)
        if provider is None:
            logger.warning(
                "Integration %s has provider_type '%s' not in registry — skipping",
                grant.integration_id, integration.provider_type,
            )
            continue

        capability = provider.get_capability(grant.capability_key)
        if capability is None:
            logger.warning(
                "Grant references capability '%s' not declared by provider '%s' — skipping",
                grant.capability_key, integration.provider_type,
            )
            continue

        from app.integrations.provider import CapabilityCategory

        tool_key = make_tool_key(grant.integration_id, grant.capability_key)

        # Deduplicate (should not occur due to unique constraint, but be safe)
        if tool_key in seen_keys:
            continue
        seen_keys.add(tool_key)

        is_read_only = capability.category in (
            CapabilityCategory.READ, CapabilityCategory.ANALYTICS
        )

        defn = DynamicToolDefinition(
            tool_key=tool_key,
            integration_id=grant.integration_id,
            tenant_id=tenant_id,
            role_key=role_key,
            capability_key=grant.capability_key,
            provider_type=integration.provider_type,
            integration_name=integration.display_name,
            description=capability.description,
            risk_level=capability.risk_level.value,
            is_read_only=is_read_only,
            input_schema=capability.input_schema,
            is_enabled=True,
        )
        tools.append(defn)

    return tools


# ── Context variable for per-request dynamic tools ────────────────────────────
# Populated by the execution router alongside the existing context vars.
# Maps tool_key → (DynamicToolDefinition, LangChain @tool adapter).
# Never process-global — only alive for the duration of a single request.

# NOTE: The actual ContextVar lives in registry.py to avoid circular imports.
# This module provides the types and the building functions.
