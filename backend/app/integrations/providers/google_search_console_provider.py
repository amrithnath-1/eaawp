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
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import google.auth.transport.requests
import google.oauth2.credentials
import google_auth_oauthlib.flow
import requests
from googleapiclient import discovery
from googleapiclient import errors as google_errors

from app.config import settings
from app.integrations.provider import (
    CapabilityCategory,
    CapabilityResult,
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
                            "description": "The Search Console property URL (e.g., sc-domain:example.com or https://www.example.com/)",
                        },
                        "start_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date (YYYY-MM-DD)",
                        },
                        "end_date": {
                            "type": "string",
                            "format": "date",
                            "description": "End date (YYYY-MM-DD)",
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
                    "required": ["site_url", "start_date", "end_date"],
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
                            "description": "The Search Console property URL",
                        },
                    },
                    "required": ["site_url"],
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
            logger.exception("Unexpected error executing GSC capability")
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

    async def _execute_search_analytics(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        """Query search performance metrics."""
        # Validate date range
        start_date = parameters["start_date"]
        end_date = parameters["end_date"]
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise GSCApiError(f"Invalid date format: {exc}")
        if (end_dt - start_dt).days > _MAX_DAYS_RANGE:
            raise GSCApiError(f"Date range exceeds maximum {_MAX_DAYS_RANGE} days")
        if end_dt > datetime.utcnow().date():
            raise GSCApiError("End date cannot be in the future")

        # Validate dimensions
        dimensions = parameters.get("dimensions", [])
        if not isinstance(dimensions, list):
            dimensions = []
        invalid_dims = set(dimensions) - _ALLOWED_DIMENSIONS
        if invalid_dims:
            raise GSCApiError(f"Unsupported dimension(s): {sorted(invalid_dims)}")

        row_limit = min(
            int(parameters.get("row_limit", 100)),
            _MAX_ROWS,
        )

        # Prepare API request body
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "dimensionFilterGroups": [],  # No filters for Phase 4
        }
        response = await self._call_api_safe(
            credentials,
            "searchAnalytics",
            "query",
            {"siteUrl": parameters["site_url"], "requestBody": body},
        )
        rows = response.get("rows", []) if isinstance(response, dict) else []
        data = []
        for row in rows[:row_limit]:
            keys = row.get("keys", [])
            data.append({
                "dimensions": keys,
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0.0),
                "position": row.get("position", 0.0),
            })
        return CapabilityResult(
            data=data,
            row_count=len(data),
            truncated=len(rows) > row_limit,
            source_label="Google Search Console",
        )

    async def _execute_site_metadata(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        """Retrieve site metadata (verification, permissions)."""
        response = await self._call_api_safe(
            credentials,
            "sites",
            "get",
            {"siteUrl": parameters["site_url"]},
        )
        # Google's response is a dict with siteUrl, permissionLevel, verification status
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

        # Build service
        service = discovery.build(
            "searchconsole",
            "v1",
            credentials=creds,
            cache_discovery=False,
        )
        api_resource = getattr(service, resource)()
        api_method = getattr(api_resource, method)

        # Execute (convert sync call to async)
        loop = asyncio.get_running_loop()
        try:
            request = api_method(**params)
            response = await loop.run_in_executor(None, request.execute)
        except google_errors.HttpError as http_err:
            # Extract safe error message without credentials
            safe_msg = f"Google API error ({http_err.status_code}): {http_err.reason}"
            raise GSCApiError(safe_msg, http_err)
        except Exception as exc:
            safe_msg = self._sanitise_error(str(exc))
            raise GSCApiError(safe_msg, exc)

        if not response and not allow_empty:
            raise GSCApiError(f"Empty response from Google API {resource}.{method}")
        return response

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
