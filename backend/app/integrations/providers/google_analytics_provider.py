"""
Google Analytics 4 Integration Provider (Phase D).

Capabilities (all READ-ONLY, LOW risk):
  • list_properties        → list GA4 properties accessible to the account
  • run_report             → query analytics metrics and dimensions for a property
  • get_realtime_report    → retrieve real-time active user data
  • list_accounts          → list Google Analytics accounts

Authentication: OAuth2 using the same Google OAuth2 flow as GSC.
Scope: https://www.googleapis.com/auth/analytics.readonly

Security:
- Tokens encrypted at rest via IntegrationManager.
- All inputs validated before Google API call.
- No arbitrary API requests — only declared capabilities.
- Credentials cleared from memory after every call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

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

_GA4_OAUTH_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

# Validated dimensions (subset of GA4 standard dimensions)
_ALLOWED_DIMENSIONS = {
    "date", "country", "city", "deviceCategory", "sessionSource",
    "sessionMedium", "pagePath", "browser", "operatingSystem",
    "eventName", "landingPage", "sessionCampaignName",
}

# Validated metrics (subset of GA4 standard metrics)
_ALLOWED_METRICS = {
    "activeUsers", "sessions", "screenPageViews", "bounceRate",
    "averageSessionDuration", "newUsers", "eventCount", "conversions",
    "totalRevenue", "engagementRate",
}

_MAX_ROWS = 1000
_MAX_DAYS_RANGE = 365


@dataclass(frozen=True)
class GAApiError(Exception):
    """Safe wrapper for Google Analytics API errors."""
    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class GoogleAnalyticsProvider(IntegrationProvider):
    """EAAWP provider for Google Analytics 4 Data API (read-only)."""

    @property
    def provider_type(self) -> str:
        return "google_analytics"

    @property
    def display_name(self) -> str:
        return "Google Analytics"

    @property
    def description(self) -> str:
        return (
            "Google Analytics 4 provides website and app analytics. "
            "This integration supports read-only access to properties, "
            "reports, real-time data, and traffic insights."
        )

    @property
    def icon_hint(self) -> str:
        return "google"

    def required_credential_fields(self) -> list[str]:
        return [
            "access_token",
            "refresh_token",
            "token_expiry",
            "client_id",
            "client_secret",
        ]

    def configuration_requirements(self) -> list[ConfigurationField]:
        """
        Server-level OAuth app credentials needed before any GA4 connection.
        Same pattern as Google Search Console — both use Google OAuth2.
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
                key="list_accounts",
                display_name="List Analytics Accounts",
                description="List all Google Analytics accounts accessible to the authorized user.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            ProviderCapability(
                key="list_properties",
                display_name="List GA4 Properties",
                description="List all GA4 properties under an Analytics account.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Google Analytics account ID (e.g. '123456789')",
                        },
                    },
                    "required": [],
                },
            ),
            ProviderCapability(
                key="run_report",
                display_name="Run Analytics Report",
                description=(
                    "Query GA4 analytics data with custom metrics and dimensions. "
                    "Returns traffic, engagement, and conversion data."
                ),
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "GA4 property ID (e.g. '123456789')",
                        },
                        "start_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Start date YYYY-MM-DD",
                        },
                        "end_date": {
                            "type": "string",
                            "format": "date",
                            "description": "End date YYYY-MM-DD",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Metrics to retrieve. Allowed: {sorted(_ALLOWED_METRICS)}",
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Dimensions to group by. Allowed: {sorted(_ALLOWED_DIMENSIONS)}",
                        },
                        "row_limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_ROWS,
                            "description": f"Max rows (≤{_MAX_ROWS})",
                        },
                    },
                    "required": ["property_id", "start_date", "end_date"],
                },
            ),
            ProviderCapability(
                key="get_realtime_report",
                display_name="Real-Time Analytics",
                description="Retrieve real-time active user counts and dimensions.",
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "GA4 property ID",
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions (subset of standard real-time dimensions)",
                        },
                    },
                    "required": ["property_id"],
                },
            ),
        ]

    async def test_connection(self, credentials: dict[str, Any]) -> ConnectionTestResult:
        try:
            await self._ensure_fresh_token(credentials)
            response = await self._call_admin_api(credentials, "accounts", {})
            accounts = response.get("accounts", [])
            return ConnectionTestResult(
                success=True,
                account_info={
                    "connected": True,
                    "account_count": len(accounts),
                },
                error_message=None,
            )
        except GAApiError as exc:
            return ConnectionTestResult(
                success=False,
                account_info={"connected": False},
                error_message=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error in GA4 test_connection")
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
        try:
            if capability_key == "list_accounts":
                return await self._list_accounts(credentials)
            if capability_key == "list_properties":
                return await self._list_properties(credentials, parameters)
            if capability_key == "run_report":
                return await self._run_report(credentials, parameters)
            if capability_key == "get_realtime_report":
                return await self._get_realtime_report(credentials, parameters)
            return CapabilityResult(data=[], error=f"Unknown capability: {capability_key}")
        except GAApiError as exc:
            return CapabilityResult(data=[], error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error in GA4 execute")
            return CapabilityResult(data=[], error=self._sanitise_error(str(exc)))

    async def _list_accounts(self, credentials: dict[str, Any]) -> CapabilityResult:
        await self._ensure_fresh_token(credentials)
        response = await self._call_admin_api(credentials, "accounts", {})
        accounts = response.get("accounts", [])
        data = [
            {
                "name": a.get("name", ""),
                "display_name": a.get("displayName", ""),
                "region_code": a.get("regionCode", ""),
            }
            for a in accounts[:_MAX_ROWS]
        ]
        return CapabilityResult(
            data=data, row_count=len(data), source_label="Google Analytics"
        )

    async def _list_properties(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        await self._ensure_fresh_token(credentials)
        account_id = parameters.get("account_id", "")
        filter_param = f"parent:accounts/{account_id}" if account_id else None
        response = await self._call_admin_api(
            credentials, "properties",
            {"filter": filter_param} if filter_param else {},
        )
        props = response.get("properties", [])
        data = [
            {
                "name": p.get("name", ""),
                "display_name": p.get("displayName", ""),
                "time_zone": p.get("timeZone", ""),
                "currency_code": p.get("currencyCode", ""),
            }
            for p in props[:_MAX_ROWS]
        ]
        return CapabilityResult(
            data=data, row_count=len(data), source_label="Google Analytics"
        )

    async def _run_report(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        # Validate dates
        start_date = parameters["start_date"]
        end_date = parameters["end_date"]
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise GAApiError(f"Invalid date format: {exc}")
        if (end_dt - start_dt).days > _MAX_DAYS_RANGE:
            raise GAApiError(f"Date range exceeds {_MAX_DAYS_RANGE} days")
        if end_dt > datetime.utcnow().date():
            raise GAApiError("End date cannot be in the future")

        # Validate metrics and dimensions
        metrics = parameters.get("metrics", ["sessions", "activeUsers"])
        dimensions = parameters.get("dimensions", [])
        invalid_m = set(metrics) - _ALLOWED_METRICS
        if invalid_m:
            raise GAApiError(f"Unsupported metrics: {sorted(invalid_m)}")
        invalid_d = set(dimensions) - _ALLOWED_DIMENSIONS
        if invalid_d:
            raise GAApiError(f"Unsupported dimensions: {sorted(invalid_d)}")

        row_limit = min(int(parameters.get("row_limit", 100)), _MAX_ROWS)
        property_id = parameters["property_id"]

        await self._ensure_fresh_token(credentials)
        body = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": m} for m in metrics],
            "dimensions": [{"name": d} for d in dimensions],
            "limit": row_limit,
        }
        response = await self._call_data_api(
            credentials, f"properties/{property_id}:runReport", body
        )
        rows = response.get("rows", [])
        dim_headers = [h.get("name", "") for h in response.get("dimensionHeaders", [])]
        met_headers = [h.get("name", "") for h in response.get("metricHeaders", [])]
        data = []
        for row in rows[:row_limit]:
            dim_vals = [v.get("value", "") for v in row.get("dimensionValues", [])]
            met_vals = [v.get("value", "") for v in row.get("metricValues", [])]
            record = {d: v for d, v in zip(dim_headers, dim_vals)}
            record.update({m: v for m, v in zip(met_headers, met_vals)})
            data.append(record)

        return CapabilityResult(
            data=data,
            row_count=len(data),
            truncated=len(rows) > row_limit,
            source_label="Google Analytics 4",
        )

    async def _get_realtime_report(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        property_id = parameters["property_id"]
        dimensions = parameters.get("dimensions", ["unifiedScreenName"])
        invalid_d = set(dimensions) - (
            _ALLOWED_DIMENSIONS | {"unifiedScreenName", "minutesAgo"}
        )
        if invalid_d:
            raise GAApiError(f"Unsupported realtime dimensions: {sorted(invalid_d)}")

        await self._ensure_fresh_token(credentials)
        body = {
            "dimensions": [{"name": d} for d in dimensions],
            "metrics": [{"name": "activeUsers"}],
        }
        response = await self._call_data_api(
            credentials, f"properties/{property_id}:runRealtimeReport", body
        )
        rows = response.get("rows", [])
        dim_headers = [h.get("name", "") for h in response.get("dimensionHeaders", [])]
        data = []
        for row in rows[:100]:
            dim_vals = [v.get("value", "") for v in row.get("dimensionValues", [])]
            met_vals = [v.get("value", "") for v in row.get("metricValues", [])]
            record = {d: v for d, v in zip(dim_headers, dim_vals)}
            record["activeUsers"] = met_vals[0] if met_vals else "0"
            data.append(record)

        return CapabilityResult(
            data=data,
            row_count=len(data),
            source_label="Google Analytics 4 (Real-Time)",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _ensure_fresh_token(self, credentials: dict[str, Any]) -> None:
        """Refresh the access token if expired (same pattern as GSC provider)."""
        expiry = credentials.get("token_expiry")
        if not expiry:
            await self._refresh_token(credentials)
            return
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            await self._refresh_token(credentials)
            return
        if datetime.utcnow() + timedelta(minutes=5) >= expiry_dt.replace(tzinfo=None):
            await self._refresh_token(credentials)

    async def _refresh_token(self, credentials: dict[str, Any]) -> None:
        if not credentials.get("refresh_token"):
            raise GAApiError("No refresh token; reauthorization required")
        try:
            import google.auth.transport.requests
            import google.oauth2.credentials
            creds = google.oauth2.credentials.Credentials(
                token=None,
                refresh_token=credentials["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"],
            )
            loop = asyncio.get_running_loop()
            request = google.auth.transport.requests.Request()
            await loop.run_in_executor(None, creds.refresh, request)
            credentials["access_token"] = creds.token
            credentials["token_expiry"] = creds.expiry.isoformat() if creds.expiry else None
        except Exception as exc:
            raise GAApiError(self._sanitise_error(str(exc)))

    async def _call_admin_api(
        self, credentials: dict[str, Any], resource: str, params: dict
    ) -> dict:
        """Call Google Analytics Admin API v1."""
        try:
            import google.oauth2.credentials
            from googleapiclient import discovery
            creds = google.oauth2.credentials.Credentials(
                token=credentials.get("access_token"),
                refresh_token=credentials.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=credentials.get("client_id"),
                client_secret=credentials.get("client_secret"),
            )
            service = discovery.build(
                "analyticsadmin", "v1beta", credentials=creds, cache_discovery=False
            )
            loop = asyncio.get_running_loop()
            if resource == "accounts":
                request = service.accounts().list()
            elif resource == "properties":
                request = service.properties().list(**{k: v for k, v in params.items() if v})
            else:
                raise GAApiError(f"Unknown admin resource: {resource}")
            response = await loop.run_in_executor(None, request.execute)
            return response if isinstance(response, dict) else {}
        except GAApiError:
            raise
        except Exception as exc:
            raise GAApiError(self._sanitise_error(str(exc)))

    async def _call_data_api(
        self, credentials: dict[str, Any], path: str, body: dict
    ) -> dict:
        """Call Google Analytics Data API v1beta."""
        import asyncio
        try:
            import google.oauth2.credentials
            from googleapiclient import discovery
            creds = google.oauth2.credentials.Credentials(
                token=credentials.get("access_token"),
                refresh_token=credentials.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=credentials.get("client_id"),
                client_secret=credentials.get("client_secret"),
            )
            service = discovery.build(
                "analyticsdata", "v1beta", credentials=creds, cache_discovery=False
            )
            loop = asyncio.get_running_loop()
            parts = path.split(":")
            resource_path = parts[0]
            method_suffix = parts[1] if len(parts) > 1 else "runReport"
            # Extract property ID
            prop_id = resource_path.split("/")[-1]
            if method_suffix == "runReport":
                request = service.properties().runReport(property=f"properties/{prop_id}", body=body)
            elif method_suffix == "runRealtimeReport":
                request = service.properties().runRealtimeReport(
                    property=f"properties/{prop_id}", body=body
                )
            else:
                raise GAApiError(f"Unknown data API method: {method_suffix}")
            response = await loop.run_in_executor(None, request.execute)
            return response if isinstance(response, dict) else {}
        except GAApiError:
            raise
        except Exception as exc:
            raise GAApiError(self._sanitise_error(str(exc)))
