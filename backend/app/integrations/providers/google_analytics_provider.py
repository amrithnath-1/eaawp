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
import re
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
_PROPERTY_ID_RE = re.compile(r"^\d{1,20}$")
_RELATIVE_DATE_RE = re.compile(r"^(\d{1,4})daysAgo$")
# What models also write: "3monthsAgo", "3 months ago", "last 90 days", "2 weeks ago", "1 year ago".
_LOOSE_RELATIVE_RE = re.compile(
    r"^(?:last\s+|past\s+)?(\d{1,4})\s*(day|week|month|year)s?(?:\s*ago)?$", re.I)


def _months_back(today: "datetime.date", months: int) -> "datetime.date":
    import calendar
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    m += 1
    return today.replace(year=y, month=m, day=min(today.day, calendar.monthrange(y, m)[1]))


def canonical_names(given: Any, allowed: set[str]) -> list[str]:
    """Dimension/metric names as the API spells them: case, "_", plural and a few synonyms are forgiven
    ("queries" → query, "search_appearance" → searchAppearance, "pages" → page). Unknown names are kept as given so the
    caller can report them."""
    if isinstance(given, str):
        given = [p.strip() for p in given.split(",") if p.strip()]
    if not isinstance(given, list):
        return []
    synonyms = {"keyword": "query", "keywords": "query", "searchquery": "query", "url": "page", "urls": "page",
                "landingpage": "page", "devicetype": "device"}
    by_key = {a.lower().replace("_", ""): a for a in allowed}
    out = []
    for g in given:
        key = str(g).strip().lower().replace("_", "").replace(" ", "")
        key = synonyms.get(key, key) if synonyms.get(key, key).lower() in by_key else key
        cand = by_key.get(key) or by_key.get(key[:-1] if key.endswith("s") else key) or \
            by_key.get(key[:-3] + "y" if key.endswith("ies") else key)
        if cand is None and key in synonyms:
            cand = by_key.get(synonyms[key])
        out.append(cand or str(g))
    return list(dict.fromkeys(out))


def resolve_report_date(value: Any, today: "datetime.date | None" = None) -> "datetime.date":
    """
    Turn a GA-style date into a concrete date.

    Accepts YYYY-MM-DD, ``today``, ``yesterday`` and ``NdaysAgo`` (the same
    relative forms the GA4 API itself understands), so "the last 7 days" can be
    asked for without the caller (or the model) knowing today's date.
    """
    today = today or datetime.utcnow().date()
    text = str(value or "").strip()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    m = _RELATIVE_DATE_RE.match(text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    loose = _LOOSE_RELATIVE_RE.match(re.sub(r"(?<=\d)(?=[a-zA-Z])|(?<=[a-z])(?=[A-Z])", " ", text).strip())
    if loose:
        n, unit = int(loose.group(1)), loose.group(2).lower()
        if unit == "day":
            return today - timedelta(days=n)
        if unit == "week":
            return today - timedelta(weeks=n)
        return _months_back(today, n * (12 if unit == "year" else 1))
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()       # also "2026-07-28T00:00:00Z"
    except ValueError:
        raise GAApiError(
            f"Invalid date '{text[:30]}'. Use YYYY-MM-DD, 'today', 'yesterday' or 'NdaysAgo'."
        )


def normalise_property_id(value: Any) -> str:
    """Accept '123456789' or 'properties/123456789'; reject anything else."""
    text = str(value or "").strip()
    if text.startswith("properties/"):
        text = text[len("properties/"):]
    if not _PROPERTY_ID_RE.match(text):
        raise GAApiError("property_id must be the numeric GA4 property ID (for example 123456789).")
    return text


@dataclass(frozen=True)
class GAApiError(Exception):
    """Safe wrapper for Google Analytics API errors."""
    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class GoogleAnalyticsProvider(IntegrationProvider):
    """EAAWP provider for Google Analytics 4 Data API (read-only)."""

    property_parameter = "property_id"

    async def list_properties(self, credentials: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"id": p["property_id"], "label": p["display_name"] or p["property_id"], "detail": p["account"]}
            for p in await self._property_summaries(credentials)
        ]

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
                            "description": (
                                "GA4 property ID (e.g. '123456789'). Optional when the "
                                "account has exactly one property."
                            ),
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date: YYYY-MM-DD, or '7daysAgo', '30daysAgo', 'yesterday', 'today'",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date: YYYY-MM-DD, or 'yesterday' / 'today' / 'NdaysAgo'",
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
                    "required": ["start_date", "end_date"],
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
                    "required": [],
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
        wanted = str(parameters.get("account_id", "") or "").replace("accounts/", "")
        data = await self._property_summaries(credentials, wanted)
        return CapabilityResult(
            data=data, row_count=len(data), source_label="Google Analytics"
        )

    async def _property_summaries(
        self, credentials: dict[str, Any], account_id: str = ""
    ) -> list[dict[str, str]]:
        """
        Every GA4 property the authorised user can read, via accountSummaries.

        (properties.list needs a ``filter`` argument and fails without one;
        accountSummaries lists accounts and their properties in one call.)
        """
        response = await self._call_admin_api(credentials, "accountSummaries", {})
        out: list[dict[str, str]] = []
        for acct in response.get("accountSummaries", []):
            acct_id = str(acct.get("account", "")).replace("accounts/", "")
            if account_id and acct_id != account_id:
                continue
            for prop in acct.get("propertySummaries", []):
                out.append({
                    "property_id": str(prop.get("property", "")).replace("properties/", ""),
                    "display_name": prop.get("displayName", ""),
                    "account": acct.get("displayName", ""),
                    "account_id": acct_id,
                })
        return out[:_MAX_ROWS]

    async def _resolve_property(self, credentials: dict[str, Any], given: Any) -> str:
        """Use the given property, or the only accessible one; never guess between several."""
        if given:
            return normalise_property_id(given)
        props = await self._property_summaries(credentials)
        if not props:
            raise GAApiError(
                "This Google account has no Google Analytics 4 properties that EAAWP can read."
            )
        if len(props) > 1:
            names = "; ".join(f"{p['display_name']} ({p['property_id']})" for p in props[:10])
            raise GAApiError(
                "Several Google Analytics properties are available, so I need to know which "
                f"one to use: {names}. Ask for the property by name or ID."
            )
        return props[0]["property_id"]

    async def _run_report(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        # Validate dates (relative forms are resolved here, server-side)
        today = datetime.utcnow().date()
        start_dt = resolve_report_date(parameters.get("start_date") or "7daysAgo", today)
        end_dt = resolve_report_date(parameters.get("end_date") or "yesterday", today)
        if end_dt < start_dt:
            raise GAApiError("end_date is before start_date")
        if (end_dt - start_dt).days > _MAX_DAYS_RANGE:
            raise GAApiError(f"Date range exceeds {_MAX_DAYS_RANGE} days")
        if end_dt > today:
            raise GAApiError("End date cannot be in the future")
        start_date, end_date = start_dt.isoformat(), end_dt.isoformat()

        # Validate metrics and dimensions
        metrics = canonical_names(parameters.get("metrics") or ["sessions", "activeUsers"], _ALLOWED_METRICS)
        dimensions = canonical_names(parameters.get("dimensions") or [], _ALLOWED_DIMENSIONS)
        invalid_m = set(metrics) - _ALLOWED_METRICS
        if invalid_m:
            raise GAApiError(f"Unsupported metrics: {sorted(invalid_m)}")
        invalid_d = set(dimensions) - _ALLOWED_DIMENSIONS
        if invalid_d:
            raise GAApiError(f"Unsupported dimensions: {sorted(invalid_d)}")

        row_limit = min(int(parameters.get("row_limit", 100)), _MAX_ROWS)

        await self._ensure_fresh_token(credentials)
        property_id = await self._resolve_property(credentials, parameters.get("property_id"))
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
            source_label=(
                f"Google Analytics 4 property {property_id}, {start_date} to {end_date}"
            ),
        )

    async def _get_realtime_report(
        self, credentials: dict[str, Any], parameters: dict[str, Any]
    ) -> CapabilityResult:
        dimensions = parameters.get("dimensions", ["unifiedScreenName"])
        invalid_d = set(dimensions) - (
            _ALLOWED_DIMENSIONS | {"unifiedScreenName", "minutesAgo"}
        )
        if invalid_d:
            raise GAApiError(f"Unsupported realtime dimensions: {sorted(invalid_d)}")

        await self._ensure_fresh_token(credentials)
        property_id = await self._resolve_property(credentials, parameters.get("property_id"))
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
        """Call Google Analytics Admin API v1beta (read-only endpoints only)."""
        if resource not in ("accounts", "accountSummaries"):
            raise GAApiError(f"Unknown admin resource: {resource}")

        def _do() -> Any:
            service = self._build("analyticsadmin", "v1beta", credentials)
            api = service.accountSummaries() if resource == "accountSummaries" else service.accounts()
            return api.list(**{k: v for k, v in params.items() if v}).execute()

        return await self._run_google(_do)

    async def _call_data_api(
        self, credentials: dict[str, Any], path: str, body: dict
    ) -> dict:
        """Call Google Analytics Data API v1beta (runReport / runRealtimeReport only)."""
        resource_path, _, method_suffix = path.partition(":")
        prop_id = normalise_property_id(resource_path.split("/")[-1])
        if method_suffix not in ("runReport", "runRealtimeReport"):
            raise GAApiError(f"Unknown data API method: {method_suffix or '(none)'}")

        def _do() -> Any:
            service = self._build("analyticsdata", "v1beta", credentials)
            props = service.properties()
            call = props.runReport if method_suffix == "runReport" else props.runRealtimeReport
            return call(property=f"properties/{prop_id}", body=body).execute()

        return await self._run_google(_do)

    def _build(self, api: str, version: str, credentials: dict[str, Any]) -> Any:
        import google.oauth2.credentials
        from googleapiclient import discovery

        creds = google.oauth2.credentials.Credentials(
            token=credentials.get("access_token"),
            refresh_token=credentials.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
        )
        return discovery.build(api, version, credentials=creds, cache_discovery=False)

    async def _run_google(self, fn: Any) -> dict:
        """Run a blocking Google client call in a worker thread; map failures to safe text."""
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, fn)
            return response if isinstance(response, dict) else {}
        except GAApiError:
            raise
        except Exception as exc:
            raise GAApiError(self._explain_google_error(exc))

    def _explain_google_error(self, exc: Exception) -> str:
        """Readable, credential-free reason for a Google API failure."""
        status = getattr(getattr(exc, "resp", None), "status", None)
        raw = self._sanitise_error(str(exc))
        if status == 401:
            return "Google rejected the stored authorisation (401). Reconnect Google Analytics."
        if status == 403:
            if "has not been used" in raw or "is disabled" in raw or "accessNotConfigured" in raw:
                return (
                    "The Google Analytics Data/Admin API is not enabled in the Google Cloud project "
                    "used for this connection (403). An admin must enable it in Google Cloud Console."
                )
            return (
                "Google denied access (403). The connected Google account may not have access to "
                "this Analytics property."
            )
        if status == 404:
            return "Google could not find that Analytics property (404). Check the property ID."
        if status == 429:
            return "Google Analytics is rate-limiting requests (429). Try again shortly."
        if status == 400:
            return f"Google rejected the report request (400): {raw[:200]}"
        return raw
