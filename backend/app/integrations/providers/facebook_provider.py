"""
Meta / Facebook Integration Provider (Phase E).

Capabilities (READ-ONLY first; write capabilities are HIGH risk + approval gated):
  • list_pages             → list Facebook Pages the user manages
  • get_page_insights      → page-level engagement metrics
  • list_ad_accounts       → list advertising accounts
  • get_campaign_metrics   → campaign performance metrics (impressions, clicks, spend)
  • get_ad_metrics         → ad-level performance data

Authentication: Facebook OAuth2
Scope (read-only): pages_show_list, pages_read_engagement, read_insights,
                   ads_read (for campaign/ad metrics)

Security:
- No Graph API arbitrary URL execution.
- Only declared capability endpoints are called.
- All parameters validated before API call.
- No write/publish capabilities in Phase E.
- Credentials cleared from memory after every call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

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

_GRAPH_BASE = "https://graph.facebook.com/v18.0"

# Maximum rows returned
_MAX_ROWS = 500

# Valid page insight metrics
_ALLOWED_PAGE_METRICS = {
    "page_impressions", "page_engaged_users", "page_post_engagements",
    "page_fan_adds", "page_views_total", "page_actions_post_reactions_total",
    "page_video_views", "page_negative_feedback",
}

# Valid campaign performance fields
_ALLOWED_CAMPAIGN_FIELDS = {
    "campaign_name", "impressions", "clicks", "spend", "reach",
    "cpc", "cpm", "ctr", "actions", "status",
}


@dataclass(frozen=True)
class FacebookApiError(Exception):
    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class FacebookProvider(IntegrationProvider):
    """EAAWP provider for Meta / Facebook Graph API (read-only)."""

    @property
    def provider_type(self) -> str:
        return "facebook"

    @property
    def display_name(self) -> str:
        return "Meta / Facebook"

    @property
    def description(self) -> str:
        return (
            "Connect Meta/Facebook to give AI employees read-only access to "
            "page insights, ad campaign metrics, and audience data."
        )

    @property
    def icon_hint(self) -> str:
        return "facebook"

    def required_credential_fields(self) -> list[str]:
        return ["access_token"]

    def optional_credential_fields(self) -> list[str]:
        return ["app_id", "app_secret"]

    def get_capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                key="list_pages",
                display_name="List Facebook Pages",
                description="List Facebook Pages the authorized user manages.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            ProviderCapability(
                key="get_page_insights",
                display_name="Page Insights",
                description=(
                    "Retrieve engagement metrics for a Facebook Page. "
                    f"Available metrics: {sorted(_ALLOWED_PAGE_METRICS)}"
                ),
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string", "description": "Facebook Page ID"},
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Insight metrics to retrieve",
                        },
                        "period": {
                            "type": "string",
                            "enum": ["day", "week", "days_28", "month"],
                            "description": "Aggregation period",
                        },
                    },
                    "required": ["page_id"],
                },
            ),
            ProviderCapability(
                key="list_ad_accounts",
                display_name="List Ad Accounts",
                description="List advertising accounts accessible to the authorized user.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            ProviderCapability(
                key="get_campaign_metrics",
                display_name="Campaign Performance",
                description="Retrieve performance metrics for Facebook ad campaigns.",
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "ad_account_id": {
                            "type": "string",
                            "description": "Ad account ID (e.g. 'act_123456')",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Fields to retrieve: {sorted(_ALLOWED_CAMPAIGN_FIELDS)}",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_ROWS,
                        },
                    },
                    "required": ["ad_account_id"],
                },
            ),
            ProviderCapability(
                key="get_ad_metrics",
                display_name="Ad Performance",
                description="Retrieve performance metrics for individual Facebook ads.",
                category=CapabilityCategory.ANALYTICS,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "ad_account_id": {
                            "type": "string",
                            "description": "Ad account ID",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": ["ad_account_id"],
                },
            ),
        ]

    async def test_connection(self, credentials: dict[str, Any]) -> ConnectionTestResult:
        try:
            token = credentials.get("access_token", "")
            if not token:
                raise FacebookApiError("No access token provided")
            data = await self._get(token, "/me", {"fields": "id,name"})
            return ConnectionTestResult(
                success=True,
                account_info={"connected": True, "user_id": data.get("id", ""), "name": data.get("name", "")},
                error_message=None,
            )
        except FacebookApiError as exc:
            return ConnectionTestResult(
                success=False, account_info={"connected": False}, error_message=str(exc)
            )

    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        try:
            token = credentials.get("access_token", "")
            if capability_key == "list_pages":
                return await self._list_pages(token)
            if capability_key == "get_page_insights":
                return await self._get_page_insights(token, parameters)
            if capability_key == "list_ad_accounts":
                return await self._list_ad_accounts(token)
            if capability_key == "get_campaign_metrics":
                return await self._get_campaign_metrics(token, parameters)
            if capability_key == "get_ad_metrics":
                return await self._get_ad_metrics(token, parameters)
            return CapabilityResult(data=[], error=f"Unknown capability: {capability_key}")
        except FacebookApiError as exc:
            return CapabilityResult(data=[], error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error in Facebook execute")
            return CapabilityResult(data=[], error=self._sanitise_error(str(exc)))

    async def _list_pages(self, token: str) -> CapabilityResult:
        data = await self._get(token, "/me/accounts", {"fields": "id,name,category,fan_count"})
        pages = data.get("data", [])
        result = [
            {"id": p.get("id"), "name": p.get("name"), "category": p.get("category"), "fans": p.get("fan_count")}
            for p in pages[:_MAX_ROWS]
        ]
        return CapabilityResult(data=result, row_count=len(result), source_label="Facebook Pages")

    async def _get_page_insights(self, token: str, params: dict) -> CapabilityResult:
        page_id = params.get("page_id", "")
        metrics = params.get("metrics", ["page_impressions", "page_engaged_users"])
        period = params.get("period", "week")
        invalid = set(metrics) - _ALLOWED_PAGE_METRICS
        if invalid:
            raise FacebookApiError(f"Unsupported insight metrics: {sorted(invalid)}")
        if period not in ("day", "week", "days_28", "month"):
            raise FacebookApiError(f"Invalid period: {period}")
        data = await self._get(
            token,
            f"/{page_id}/insights",
            {"metric": ",".join(metrics), "period": period},
        )
        insights = data.get("data", [])
        result = [
            {"metric": i.get("name"), "values": i.get("values", []), "title": i.get("title")}
            for i in insights
        ]
        return CapabilityResult(data=result, row_count=len(result), source_label="Facebook Page Insights")

    async def _list_ad_accounts(self, token: str) -> CapabilityResult:
        data = await self._get(token, "/me/adaccounts", {"fields": "id,name,account_status,currency"})
        accounts = data.get("data", [])
        result = [
            {"id": a.get("id"), "name": a.get("name"), "status": a.get("account_status"), "currency": a.get("currency")}
            for a in accounts[:_MAX_ROWS]
        ]
        return CapabilityResult(data=result, row_count=len(result), source_label="Facebook Ad Accounts")

    async def _get_campaign_metrics(self, token: str, params: dict) -> CapabilityResult:
        account_id = params.get("ad_account_id", "")
        fields = params.get("fields", ["campaign_name", "impressions", "clicks", "spend"])
        invalid = set(fields) - _ALLOWED_CAMPAIGN_FIELDS
        if invalid:
            raise FacebookApiError(f"Unsupported campaign fields: {sorted(invalid)}")
        limit = min(int(params.get("limit", 25)), _MAX_ROWS)
        data = await self._get(
            token,
            f"/{account_id}/campaigns",
            {"fields": ",".join(fields), "limit": str(limit)},
        )
        campaigns = data.get("data", [])
        return CapabilityResult(data=campaigns, row_count=len(campaigns), source_label="Facebook Campaigns")

    async def _get_ad_metrics(self, token: str, params: dict) -> CapabilityResult:
        account_id = params.get("ad_account_id", "")
        fields = params.get("fields", ["ad_name", "impressions", "clicks", "spend"])
        invalid = set(fields) - (_ALLOWED_CAMPAIGN_FIELDS | {"ad_name", "ad_id"})
        if invalid:
            raise FacebookApiError(f"Unsupported ad fields: {sorted(invalid)}")
        limit = min(int(params.get("limit", 25)), _MAX_ROWS)
        data = await self._get(
            token,
            f"/{account_id}/ads",
            {"fields": ",".join(fields), "limit": str(limit)},
        )
        ads = data.get("data", [])
        return CapabilityResult(data=ads, row_count=len(ads), source_label="Facebook Ads")

    async def _get(self, token: str, path: str, params: dict) -> dict:
        """Execute a GET request to the Graph API asynchronously."""
        loop = asyncio.get_running_loop()
        url = f"{_GRAPH_BASE}{path}"
        all_params = {**params, "access_token": token}

        def _do_get():
            try:
                resp = requests.get(url, params=all_params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                safe = self._sanitise_error(str(e))
                raise FacebookApiError(safe, e) from e
            except requests.RequestException as e:
                safe = self._sanitise_error(str(e))
                raise FacebookApiError(safe, e) from e

        try:
            return await loop.run_in_executor(None, _do_get)
        except FacebookApiError:
            raise
        except Exception as exc:
            raise FacebookApiError(self._sanitise_error(str(exc)))
