"""
Google Search Console IntegrationProvider.

Phase 4 real external integration proof.

Capabilities:
  • list_sites        → retrieves authorized Search Console properties
  • get_search_analytics → query search performance metrics
  • get_site_metadata → retrieve property metadata

Authentication: OAuth2 (client_id/secret from server environment, no user password).
Token storage: refresh_token / access_token / token_expiry stored as encrypted credentials.
Secrets never exposed to LLM or frontend.

Capabilities are READ‑ONLY (LOW risk) — no website modification, publishing, or destructive operations.

Provider responsibilities:
  1. Request only the minimum required scope (https://www.googleapis.com/auth/webmasters.readonly).
  2. Validate token freshness and automatically refresh expired access tokens.
  3. Map capability_key to Google Search Console API endpoints.
  4. Enforce bounds on date ranges, row limits, and allowed dimensions.
  5. Sanitise errors — never leak OAuth tokens, authorization codes, or client secrets.
  6. Return CapabilityResult with safe, bounded data suitable for LLM consumption.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import google.auth.transport.requests
import google.oauth2.credentials
import google_auth_oauthlib.flow
import requests
from googleapiclient import discovery
from googleapiclient import errors as google_errors

from app.config import settings
from app.integrations.providers.google_analytics_provider import GAApiError, resolve_report_date
from app.integrations.provider import (
    CapabilityCategory,
    CapabilityResult,
    ConfigurationField,
    ConnectionTestResult,
    IntegrationProvider,
    ProviderCapability,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# Required OAuth2 scope for read-only Search Console access.
_GSC_OAUTH_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# Maximum row limit for get_search_analytics.
_MAX_ROWS = 1000

# Supported dimensions (from Google Search Console API).
_ALLOWED_DIMENSIONS = {
    "query",
    "page",
    "country",
    "device",
    "searchAppearance",
    "date",
}

# Parameter validation bounds.
_MAX_DAYS_RANGE = 365  # cannot query more than 1 year of historical data


@dataclass(frozen=True)
class GSCApiError(Exception):
    """Safe wrapper for Google API errors."""

    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class GoogleSearchConsoleProvider(IntegrationProvider):
    """EAAWP provider for Google Search Console read-only API."""

    property_parameter = "site_url"

    def __init__(self) -> None:
        # No persistent client — each request builds fresh credentials from stored tokens.
        pass

    @property
    def provider_type(self) -> str:
        return "google_search_console"

    @property
    def display_name(self) -> str:
        return "Google Search Console"

    @property
    def description(self) -> str:
        return (
            "Google Search Console provides insights into how your website appears "
            "in Google Search. This integration supports read-only access to "
            "search analytics, site lists, and property metadata."
        )

    @property
    def icon_hint(self) -> str:
        return "google"

    def required_credential_fields(self) -> list[str]:
        # OAuth2 flow stores tokens after callback.
        return [
            "access_token",
            "refresh_token",
            "token_expiry",
            "client_id",
            "client_secret",
        ]

    def optional_credential_fields(self) -> list[str]:
        return []

    def configuration_requirements(self) -> list[ConfigurationField]:
        """
        Server-level OAuth app credentials needed before any GSC connection.
        These are registered once per deployment in Google Cloud Console.
        SECRET fields are stored encrypted — values never returned to LLM.
        """
        return [
            ConfigurationField(
                key="client_id",
                display_name="Google Client ID",
                description="OAuth 2.0 Client ID from Google Cloud Console.",
                is_secret=False,
                required=True,
                field_type="identifier",
                placeholder="*.apps.googleusercontent.com",
                help_url="https://console.cloud.google.com/apis/credentials",
            ),
            ConfigurationField(
                key="client_secret",
                display_name="Google Client Secret",
                description="OAuth 2.0 Client Secret — stored encrypted, never shown.",
                is_secret=True,
                required=True,
                field_type="secret",
                placeholder="GOCSPX-...",
                help_url="https://console.cloud.google.com/apis/credentials",
            ),
            ConfigurationField(
                key="redirect_uri",
                display_name="Authorized Redirect URI",
                description="Must match exactly what is registered in Google Cloud Console.",
                is_secret=False,
                required=True,
                field_type="url",
                placeholder="http://localhost:8000/api/v1/oauth/google/callback",
                help_url="https://console.cloud.google.com/apis/credentials",
            ),
        ]

    def get_capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                key="list_sites",
                display_name="List Search Console Sites",
                description=(
                    "Retrieve the list of Search Console properties (sites) "
                    "accessible to the connected Google account."
                ),
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            ProviderCapability(
                key="get_search_analytics",
                display_name="Get Search Analytics",
                description=(
                    "Query Google Search Console search performance metrics "
                    "for an authorized property. Supports dimensions such as "
                    "query, page, country, device, and date."
                ),
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": (
                                "The Search Console property (sc-domain:example.com or https://www.example.com/). "
                                "Omit to use the company's selected property."
                            ),
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date: YYYY-MM-DD or a relative form such as '28daysAgo'. Defaults to 28daysAgo.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": (
                                "End date: YYYY-MM-DD or 'yesterday' / 'NdaysAgo'. Defaults to 3daysAgo "
                                "because Search Console data lags by 2-3 days."
                            ),
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Optional dimensions to group by. Allowed values: {sorted(_ALLOWED_DIMENSIONS)}",
                        },
                        "row_limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_ROWS,
                            "description": f"Maximum number of rows to return (≤{_MAX_ROWS})",
                        },
                    },
                    "required": [],
                },
            ),
            ProviderCapability(
                key="get_site_metadata",
                display_name="Get Site Metadata",
                description="Retrieve metadata about a specific Search Console property (verification status, permissions).",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_url": {
                            "type": "string",
                            "description": "The Search Console property URL. Omit to use the selected property.",
                        },
                    },
                    "required": [],
                },
            ),
        ]

    async def test_connection(self, credentials: dict[str, Any]) -> ConnectionTestResult:
        """Verify OAuth2 tokens are valid by making a minimal API call."""
        try:
            site = await self._call_api_safe(
                credentials,
                "sites",
                "list",
                {},
                allow_empty=True,
            )
            # Google returns a list of {'siteUrl': ..., 'permissionLevel': ...}
            sites = site.get("siteEntry", []) if isinstance(site, dict) else site
            account_info = {
                "connected": True,
                "site_count": len(sites) if isinstance(sites, list) else 0,
            }
            return ConnectionTestResult(
                success=True,
                account_info=account_info,
                error_message=None,
            )
        except GSCApiError as exc:
            return ConnectionTestResult(
                success=False,
                account_info={"connected": False},
                error_message=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error testing GSC connection")
            return ConnectionTestResult(
                success=False,
                account_info={"connected": False},
                error_message=self._sanitise_error(str(exc)),
            )

    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        """Execute a GSC capability, refreshing tokens if necessary."""
        try:
            if capability_key == "list_sites":
                return await self._execute_list_sites(credentials)
            if capability_key == "get_search_analytics":
                return await self._execute_search_analytics(credentials, parameters)
            if capability_key == "get_site_metadata":
                return await self._execute_site_metadata(credentials, parameters)

            return CapabilityResult(
                data=f"Unknown capability '{capability_key}'",
                error="Capability not implemented.",
            )
        except GSCApiError as exc:
            return CapabilityResult(
                data=[],
                error=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected error executing GSC capability (%s)", type(exc).__name__)
            return CapabilityResult(
                data=[],
                error=self._sanitise_error(str(exc)),
            )

    async def _execute_list_sites(
        self, credentials: dict[str, Any]
    ) -> CapabilityResult:
        """List authorized Search Console properties."""
        response = await self._call_api_safe(
            credentials,
            "sites",
            "list",
            {},
            allow_empty=True,
        )
        # The API returns {'siteEntry': [{'siteUrl': ..., 'permissionLevel': ...}]}
        sites = response.get("siteEntry", []) if isinstance(response, dict) else response
        if not isinstance(sites, list):
            sites = []
        data = [
            {"site_url": entry.get("siteUrl", ""), "permission": entry.get("permissionLevel", "")}
            for entry in sites[: _MAX_ROWS]
        ]
        return CapabilityResult(
            data=data,
            row_count=len(data),
            truncated=len(sites) > _MAX_ROWS,
            source_label="Google Search Console",
        )

    async def list_properties(self, credentials: dict[str, Any]) -> list[dict[str, str]]:
        """Properties this account can query (verified owners/users only)."""
        response = await self._call_api_safe(credentials, "sites", "list", {}, allow_empty=True)
        entries = response.get("siteEntry", []) if isinstance(response, dict) else []
        out = []
        for e in entries if isinstance(entries, list) else []:
            if e.get("permissionLevel") == "siteUnverifiedUser":
                continue   # cannot query data for a site the user has not verified
            out.append({"id": e.get("siteUrl", ""), "label": e.get("siteUrl", ""),
                        "detail": e.get("permissionLevel", "")})
        return out[:_MAX_ROWS]

    async def _resolve_site(self, credentials: dict[str, Any], given: Any) -> str:
        """The given property, else the only accessible one; never guess between several."""
        if given:
            return self._validate_site_url(given)
        props = await self.list_properties(credentials)
        if not props:
            raise GSCApiError("This Google account has no verified Search Console properties that EAAWP can read.")
        if len(props) > 1:
            names = "; ".join(p["id"] for p in props[:10])
            raise GSCApiError(
                "Several Search Console properties are available, so I need to know which one to use: "
                f"{names}. Ask for the property by name, or have an administrator select a default."
            )
        return props[0]["id"]

    @staticmethod
    def _validate_site_url(value: Any) -> str:
        text = str(value or "").strip()
        if text.startswith("sc-domain:") and len(text) > len("sc-domain:") and " " not in text:
            return text
        if re.match(r"^https?://[^\s/]+(/\S*)?$", text):
            return text
        raise GSCApiError(
            "site_url must be a Search Console property such as sc-domain:example.com or https://www.example.com/."
        )

    @staticmethod
    def _date(value: Any, today: Any) -> Any:
        try:
            return resolve_report_date(value, today)
        except GAApiError as exc:
            raise GSCApiError(str(exc))

    async def _execute_search_analytics(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        """Query search performance metrics."""
        today = datetime.utcnow().date()
        start_dt = self._date(parameters.get("start_date") or "28daysAgo", today)
        end_dt = self._date(parameters.get("end_date") or "3daysAgo", today)
        if end_dt < start_dt:
            raise GSCApiError("end_date is before start_date")
        if (end_dt - start_dt).days > _MAX_DAYS_RANGE:
            raise GSCApiError(f"Date range exceeds maximum {_MAX_DAYS_RANGE} days")
        if end_dt > today:
            raise GSCApiError("End date cannot be in the future")

        dimensions = parameters.get("dimensions", [])
        if not isinstance(dimensions, list):
            dimensions = []
        invalid_dims = set(dimensions) - _ALLOWED_DIMENSIONS
        if invalid_dims:
            raise GSCApiError(f"Unsupported dimension(s): {sorted(invalid_dims)}")

        try:
            row_limit = max(1, min(int(parameters.get("row_limit", 100)), _MAX_ROWS))
        except (TypeError, ValueError):
            raise GSCApiError("row_limit must be a whole number")

        site = await self._resolve_site(credentials, parameters.get("site_url"))
        body = {
            "startDate": start_dt.isoformat(),
            "endDate": end_dt.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "dimensionFilterGroups": [],  # read-only, unfiltered
        }
        response = await self._call_api_safe(
            credentials, "searchAnalytics", "query", {"siteUrl": site, "requestBody": body},
            allow_empty=True,   # Google omits "rows" (or returns {}) when there is no data
        )
        rows = response.get("rows", []) if isinstance(response, dict) else []
        data = []
        for row in rows[:row_limit]:
            keys = row.get("keys", [])
            item: dict[str, Any] = {}
            for name, key in zip(dimensions, keys):
                item[name] = key
            item.update({
                "dimensions": keys,
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0.0),
                "position": row.get("position", 0.0),
            })
            data.append(item)
        label = (
            f"Google Search Console (property {site}, {start_dt.isoformat()} to {end_dt.isoformat()}; "
            "Google reports this data with a 2-3 day delay)"
        )
        return CapabilityResult(
            data=data, row_count=len(data), truncated=len(rows) > row_limit, source_label=label,
        )

    async def _execute_site_metadata(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        """Retrieve site metadata (verification, permissions)."""
        site = await self._resolve_site(credentials, parameters.get("site_url"))
        response = await self._call_api_safe(credentials, "sites", "get", {"siteUrl": site})
        return CapabilityResult(
            data=dict(response) if isinstance(response, dict) else response,
            row_count=1,
            source_label="Google Search Console",
        )

    # ────────── OAuth2 credential refresh & API client helpers ──────────

    async def _call_api_safe(
        self,
        credentials: dict[str, Any],
        resource: str,
        method: str,
        params: dict[str, Any],
        allow_empty: bool = False,
    ) -> Any:
        """Build a Google API client with refreshed tokens and execute a call."""
        # Refresh tokens if expired (credentials dict is mutated in place)
        if await self._should_refresh_token(credentials):
            await self._refresh_access_token(credentials)

        creds = google.oauth2.credentials.Credentials(
            token=credentials.get("access_token"),
            refresh_token=credentials.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
        )

        loop = asyncio.get_running_loop()

        def _run() -> Any:
            # Building the client can hit the network; keep it off the event loop.
            service = discovery.build("searchconsole", "v1", credentials=creds, cache_discovery=False)
            return getattr(getattr(service, resource)(), method)(**params).execute()

        try:
            response = await loop.run_in_executor(None, _run)
        except google_errors.HttpError as http_err:
            status = getattr(http_err, "status_code", None) or getattr(getattr(http_err, "resp", None), "status", None)
            msg = self._explain_http_error(status, str(http_err.reason or ""))
            raise GSCApiError(self._scrub(msg, credentials), http_err)
        except Exception as exc:
            safe_msg = self._scrub(self._sanitise_error(str(exc)), credentials)
            raise GSCApiError(safe_msg, exc)

        if not response and not allow_empty:
            raise GSCApiError(f"Empty response from Google API {resource}.{method}")
        return response

    @staticmethod
    def _scrub(message: str, credentials: dict[str, Any]) -> str:
        """Remove any stored credential value that an upstream error happened to echo."""
        for key in ("access_token", "refresh_token", "client_secret", "client_id"):
            value = credentials.get(key)
            if isinstance(value, str) and len(value) >= 8:
                message = message.replace(value, "[REDACTED]")
        return message

    def _explain_http_error(self, status: Any, reason: str) -> str:
        """Readable, credential-free reason. Keeps the 'Google API error (N)' prefix."""
        reason = self._sanitise_error(reason)[:200]
        base = f"Google API error ({status}): {reason}"
        if status == 401:
            return f"{base}. Google rejected the stored authorisation; reconnect Search Console."
        if status == 403:
            low = reason.lower()
            if "has not been used" in low or "disabled" in low or "accessnotconfigured" in low:
                return (f"{base}. The Search Console API is not enabled in the Google Cloud project "
                        "used for this connection; an administrator must enable it.")
            return (f"{base}. The connected Google account does not have permission for this "
                    "Search Console property.")
        if status == 404:
            return f"{base}. Search Console could not find that property."
        if status == 429:
            return f"{base}. Search Console is rate-limiting requests; try again shortly."
        return base

    async def _should_refresh_token(self, credentials: dict[str, Any]) -> bool:
        """Check if access_token is expired or about to expire (5‑minute buffer)."""
        expiry = credentials.get("token_expiry")
        if not expiry:
            return True
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            return True
        buffer = timedelta(minutes=5)
        now = datetime.now(timezone.utc) if expiry_dt.tzinfo else datetime.utcnow()
        return now + buffer >= expiry_dt.replace(tzinfo=None) if not expiry_dt.tzinfo else datetime.now(timezone.utc) + buffer >= expiry_dt

    async def _refresh_access_token(self, credentials: dict[str, Any]) -> None:
        """Refresh the access token using the stored refresh token."""
        if not credentials.get("refresh_token"):
            raise GSCApiError("No refresh token available; reauthorization required")

        creds = google.oauth2.credentials.Credentials(
            token=None,  # Old token may be expired
            refresh_token=credentials["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )

        loop = asyncio.get_running_loop()
        try:
            request = google.auth.transport.requests.Request()
            await loop.run_in_executor(None, creds.refresh, request)
        except Exception as exc:
            safe_msg = self._sanitise_error(str(exc))
            raise GSCApiError(f"Failed to refresh access token: {safe_msg}")

        # Update credentials dict in place
        credentials.update({
            "access_token": creds.token,
            "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
        })
        logger.debug("Refreshed Google access token")
