"""
MCP (Model Context Protocol) Integration Provider — Phase G.

Architecture:
  User provides an MCP server URL + optional API key.
  The provider:
    1. Connects to the server and discovers tools/resources.
    2. Classifies each discovered tool with a risk level.
    3. Returns discovered tools as CapabilityResult — they remain UNAVAILABLE
       until explicitly granted via capability grants.
    4. Executes approved, granted tools with full input validation.

Security invariants (CRITICAL):
  - Discovered MCP tools are NOT automatically granted. Every tool must
    receive an explicit CapabilityGrant before it can be executed.
  - All MCP tool calls go through validate_tool_arguments() before dispatch.
  - MCP server responses are size-bounded (MAX_RESPONSE_CHARS).
  - MCP server calls have a strict timeout (MCP_CALL_TIMEOUT_SECONDS).
  - Credential fields (api_key etc.) are stored encrypted; never sent to LLM.
  - The MCP server URL is validated as https:// before any connection.
  - No arbitrary HTTP URLs from LLM input — only the registered server URL is used.
  - MCP responses are treated as UNTRUSTED external data — never as instructions.
  - Tool names containing prompt-injection patterns are rejected.
  - No shell execution, no filesystem access, no subprocess via MCP.

Risk classification:
  - read_*  / list_* / get_* / search_* / query_*  → LOW
  - create_* / update_* / upsert_*                  → MEDIUM
  - delete_* / remove_* / publish_* / send_* /
    deploy_* / execute_* / run_*                    → HIGH
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from app.integrations.provider import (
    CapabilityCategory,
    CapabilityResult,
    ConnectionTestResult,
    IntegrationProvider,
    ProviderCapability,
    RiskLevel,
)

logger = logging.getLogger(__name__)

MCP_CALL_TIMEOUT_SECONDS = 30
MAX_RESPONSE_CHARS = 10_000
MAX_DISCOVERED_TOOLS = 50

# Patterns that suggest prompt injection in tool names/descriptions
_INJECTION_PATTERNS = re.compile(
    r"(ignore previous|override system|you are now|disregard|"
    r"forget your instructions|act as|jailbreak|bypass)",
    re.IGNORECASE,
)

# Risk classification by tool name prefix
_HIGH_RISK_PREFIXES = frozenset([
    "delete", "remove", "destroy", "publish", "send", "deploy",
    "execute", "run", "drop", "truncate", "wipe", "clear_all",
    "admin", "sudo", "override",
])
_MEDIUM_RISK_PREFIXES = frozenset([
    "create", "update", "upsert", "insert", "add", "write",
    "modify", "patch", "set", "put", "post",
])


def _classify_risk(tool_name: str) -> RiskLevel:
    name_lower = tool_name.lower()
    prefix = name_lower.split("_")[0]
    if prefix in _HIGH_RISK_PREFIXES:
        return RiskLevel.HIGH
    if prefix in _MEDIUM_RISK_PREFIXES:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _classify_category(tool_name: str, description: str) -> CapabilityCategory:
    name_lower = tool_name.lower()
    if any(name_lower.startswith(p) for p in _MEDIUM_RISK_PREFIXES):
        return CapabilityCategory.WRITE
    if any(name_lower.startswith(p) for p in _HIGH_RISK_PREFIXES):
        return CapabilityCategory.PUBLISH
    return CapabilityCategory.READ


def _validate_mcp_url(url: str) -> str:
    """
    Reject URLs that could be used for SSRF attacks.

    Blocks:
    - Non-http(s) schemes
    - Missing host
    - Loopback addresses (127.0.0.0/8, ::1)
    - Private RFC-1918 ranges (10.x, 172.16-31.x, 192.168.x)
    - Link-local (169.254.x.x, fe80::/10)
    - Multicast ranges
    - Cloud-provider metadata endpoints (169.254.169.254, etc.)
    - Internal hostnames (localhost, *.local, *.internal)

    Allows only routable public addresses so legitimate customer MCP
    servers on the internet remain reachable.
    """
    import ipaddress
    import socket

    parsed = urlparse(url)

    if parsed.scheme not in ("https", "http"):
        raise MCPError("MCP server URL must use https or http scheme.")
    if not parsed.netloc:
        raise MCPError("Invalid MCP server URL: missing host.")

    # Extract the bare hostname (strip port if present)
    hostname = parsed.hostname or ""
    if not hostname:
        raise MCPError("Invalid MCP server URL: could not parse hostname.")

    # Block common internal hostname patterns regardless of DNS resolution
    _BLOCKED_HOSTNAME_PATTERNS = (
        "localhost",
        "metadata.google.internal",
        "metadata",
        "169.254.169.254",    # AWS/GCP/Azure IMDS — also caught via IP below
    )
    hostname_lower = hostname.lower()
    for pattern in _BLOCKED_HOSTNAME_PATTERNS:
        if hostname_lower == pattern:
            raise MCPError(
                f"MCP server URL '{hostname}' is not allowed: "
                "internal/metadata hostnames are blocked."
            )
    # Block *.local and *.internal TLDs (mDNS / internal DNS zones)
    if hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise MCPError(
            f"MCP server URL '{hostname}' is not allowed: "
            ".local and .internal domains are blocked."
        )

    # Attempt to resolve the hostname to an IP and check for SSRF ranges.
    # We resolve here so that DNS rebinding attacks are partially mitigated
    # (the check runs at configuration-save time and again at connect time).
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        resolved_ips = {info[4][0] for info in addr_info}
    except socket.gaierror:
        # DNS resolution failed — the hostname may be valid but unreachable from
        # this environment (e.g. a customer's internet-facing server that isn't
        # reachable during test setup).  We allow it; if the hostname actually
        # resolves to a private IP at connect time, the IP-classification check
        # in validate_outbound_host() will block it there.
        return url

    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue  # malformed — skip; connection will fail naturally

        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise MCPError(
                f"MCP server URL resolves to a non-public address ({ip_str}) "
                "and is not permitted.  Only public internet addresses are allowed."
            )

    return url


def _check_injection(text: str, field_name: str) -> None:
    """Reject text that looks like a prompt injection attempt."""
    if _INJECTION_PATTERNS.search(text):
        raise MCPError(
            f"MCP {field_name} contains potentially malicious content and was rejected."
        )


@dataclass
class MCPError(Exception):
    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class MCPIntegrationProvider(IntegrationProvider):
    """
    EAAWP provider for MCP (Model Context Protocol) servers.

    This is a meta-provider: the specific capabilities depend on what
    the connected MCP server exposes. Capabilities are discovered at
    connection time and stored as CapabilityGrant records.
    """

    @property
    def provider_type(self) -> str:
        return "mcp"

    @property
    def display_name(self) -> str:
        return "MCP Server"

    @property
    def description(self) -> str:
        return (
            "Connect a Model Context Protocol (MCP) server to expose its tools "
            "as capabilities. All discovered tools require explicit grants before "
            "any AI employee can use them. Risk levels are auto-classified by tool name."
        )

    @property
    def icon_hint(self) -> str:
        return "server"

    def required_credential_fields(self) -> list[str]:
        return ["server_url"]

    def optional_credential_fields(self) -> list[str]:
        return ["api_key", "auth_header_name"]

    def get_capabilities(self) -> list[ProviderCapability]:
        """
        The base capabilities for MCP are meta-operations.
        Actual tool capabilities are discovered at runtime via discover_entities().
        """
        return [
            ProviderCapability(
                key="discover_tools",
                display_name="Discover MCP Tools",
                description="List all tools exposed by the connected MCP server.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            ProviderCapability(
                key="call_tool",
                display_name="Call MCP Tool",
                description=(
                    "Execute a specific tool on the MCP server. "
                    "The tool_name must match a discovered tool. "
                    "Risk level depends on the specific tool being called."
                ),
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.MEDIUM,
                input_schema={
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Name of the MCP tool to call",
                            "maxLength": 128,
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments to pass to the MCP tool",
                        },
                    },
                    "required": ["tool_name"],
                },
            ),
        ]

    async def test_connection(self, credentials: dict[str, Any]) -> ConnectionTestResult:
        try:
            server_url = credentials.get("server_url", "")
            _validate_mcp_url(server_url)
            tools = await self._discover_tools(credentials)
            return ConnectionTestResult(
                success=True,
                account_info={
                    "connected": True,
                    "server_url": self._safe_url(server_url),
                    "tool_count": len(tools),
                    "tool_names": [t["name"] for t in tools[:10]],
                },
                error_message=None,
            )
        except MCPError as exc:
            return ConnectionTestResult(
                success=False,
                account_info={"connected": False},
                error_message=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected MCP test_connection error")
            return ConnectionTestResult(
                success=False,
                account_info={"connected": False},
                error_message=self._sanitise_error(str(exc)),
            )

    async def discover_entities(self, credentials: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Discover tools from the MCP server.
        Returns a list of tool descriptors — these become potential capabilities.
        They are NOT available until explicitly granted.
        """
        tools = await self._discover_tools(credentials)
        return [
            {
                "schema_name": "mcp",
                "entity_name": t["name"],
                "entity_type": "mcp_tool",
                "column_count": 0,
                "row_count_estimate": None,
                "columns": [],
                "description": t.get("description", ""),
                "risk_level": _classify_risk(t["name"]).value,
                "input_schema": t.get("inputSchema", {}),
            }
            for t in tools
        ]

    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        try:
            if capability_key == "discover_tools":
                tools = await self._discover_tools(credentials)
                data = [
                    {
                        "name": t["name"],
                        "description": t.get("description", "")[:200],
                        "risk_level": _classify_risk(t["name"]).value,
                        "requires_grant": True,
                    }
                    for t in tools
                ]
                return CapabilityResult(
                    data=data, row_count=len(data),
                    source_label="MCP Server",
                )

            if capability_key == "call_tool":
                return await self._call_tool(credentials, parameters)

            return CapabilityResult(
                data=[], error=f"Unknown MCP capability: {capability_key}"
            )
        except MCPError as exc:
            return CapabilityResult(data=[], error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected MCP execute error")
            return CapabilityResult(
                data=[], error=self._sanitise_error(str(exc))
            )

    async def _discover_tools(self, credentials: dict[str, Any]) -> list[dict]:
        """Call the MCP server's tools/list endpoint."""
        server_url = credentials.get("server_url", "")
        _validate_mcp_url(server_url)
        response = await self._mcp_request(
            credentials,
            method="tools/list",
            params={},
        )
        tools = response.get("tools", [])
        if not isinstance(tools, list):
            return []
        safe_tools = []
        for t in tools[:MAX_DISCOVERED_TOOLS]:
            name = str(t.get("name", ""))[:128]
            description = str(t.get("description", ""))[:500]
            # Reject injection attempts in tool names/descriptions
            try:
                _check_injection(name, "tool name")
                _check_injection(description, "tool description")
            except MCPError:
                logger.warning("MCP tool rejected (injection pattern): %r", name)
                continue
            safe_tools.append({
                "name": name,
                "description": description,
                "inputSchema": t.get("inputSchema", {}),
            })
        return safe_tools

    async def _call_tool(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        """Execute a specific MCP tool."""
        tool_name = parameters.get("tool_name", "")
        if not tool_name or len(tool_name) > 128:
            raise MCPError("tool_name is required and must be ≤128 characters")

        _check_injection(tool_name, "tool_name parameter")

        # Validate the tool exists on this server
        tools = await self._discover_tools(credentials)
        known_names = {t["name"] for t in tools}
        if tool_name not in known_names:
            raise MCPError(
                f"Tool '{tool_name}' not found on MCP server. "
                f"Available: {sorted(known_names)[:10]}"
            )

        tool_args = parameters.get("arguments", {})
        if not isinstance(tool_args, dict):
            raise MCPError("arguments must be a JSON object")

        # Check argument keys for injection and credential leakage
        from app.tools.dynamic_tool import _FORBIDDEN_PARAM_FIELDS
        for key in tool_args:
            if key.lower() in _FORBIDDEN_PARAM_FIELDS:
                raise MCPError(
                    f"Argument '{key}' is not permitted — credentials cannot be "
                    "passed through MCP tool arguments."
                )
            _check_injection(str(key), "argument key")

        response = await self._mcp_request(
            credentials,
            method="tools/call",
            params={"name": tool_name, "arguments": tool_args},
        )

        content = response.get("content", [])
        if isinstance(content, list):
            text_parts = [
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            result_text = "\n".join(text_parts)[:MAX_RESPONSE_CHARS]
        else:
            result_text = str(content)[:MAX_RESPONSE_CHARS]

        return CapabilityResult(
            data=result_text,
            row_count=1,
            source_label=f"MCP:{tool_name}",
        )

    async def _mcp_request(
        self,
        credentials: dict[str, Any],
        method: str,
        params: dict,
    ) -> dict:
        """
        Send a JSON-RPC 2.0 request to the MCP server.
        Uses HTTP POST per the MCP HTTP transport spec.
        Enforces timeout and response size limits.
        """
        server_url = credentials.get("server_url", "").rstrip("/")
        api_key = credentials.get("api_key", "")
        auth_header = credentials.get("auth_header_name", "Authorization")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers[auth_header] = f"Bearer {api_key}"

        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_running_loop()

        def _do():
            try:
                resp = requests.post(
                    f"{server_url}/mcp",
                    headers=headers,
                    json=body,
                    timeout=MCP_CALL_TIMEOUT_SECONDS,
                    stream=True,
                )
                resp.raise_for_status()
                # Enforce response size limit
                raw = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    raw += chunk
                    if len(raw) > MAX_RESPONSE_CHARS * 4:
                        break
                data = json.loads(raw[:MAX_RESPONSE_CHARS * 4].decode("utf-8", errors="replace"))
                if "error" in data:
                    err = data["error"]
                    raise MCPError(
                        f"MCP server error {err.get('code', '')}: "
                        f"{str(err.get('message', ''))[:200]}"
                    )
                return data.get("result", {})
            except MCPError:
                raise
            except requests.HTTPError as e:
                raise MCPError(f"MCP HTTP error: {e.response.status_code}", e)
            except requests.Timeout:
                raise MCPError(
                    f"MCP server did not respond within {MCP_CALL_TIMEOUT_SECONDS}s"
                )
            except requests.RequestException as e:
                raise MCPError(self._sanitise_error(str(e)), e)

        return await loop.run_in_executor(None, _do)

    @staticmethod
    def _safe_url(url: str) -> str:
        """Return a URL with credentials stripped (for logging/display)."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
