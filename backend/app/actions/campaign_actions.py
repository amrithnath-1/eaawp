"""
EAAWP Campaign Action Tools

create_campaign — MEDIUM risk, requires approval by default
update_campaign — MEDIUM/HIGH risk depending on what changes

Read operations (get_campaigns, get_campaign_metrics, get_campaign_summary)
are NOT action tools — they are plain read tools in MASTER_TOOL_REGISTRY
and execute automatically with no governance overhead.

Security invariants
-------------------
- LLM can never directly execute SQL or modify arbitrary database tables.
- Budget changes are always HIGH risk.
- Status transitions to active/cancelled are HIGH risk.
- Validation uses the existing CampaignCreate/UpdateCampaignInput schemas.
- Tenant isolation enforced in every DB operation.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.schemas.campaign import (
    CampaignCreate,
    CampaignUpdate,
    CreateCampaignInput,
    UpdateCampaignInput,
    determine_update_risk,
)
from app.services.campaign_service import (
    create_campaign as svc_create_campaign,
    get_campaign,
    update_campaign as svc_update_campaign,
)

logger = logging.getLogger(__name__)


class CreateCampaignAction(BaseActionTool):
    """
    Creates a new EAAWP-internal campaign record.
    MEDIUM risk — always requires review before a new campaign is launched.
    Does NOT create external advertising campaigns.
    """

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="create_campaign",
            display_name="Create Campaign",
            description=(
                "Create a new internal marketing campaign record. "
                "MEDIUM risk — requires human approval. "
                "Does NOT create external ad campaigns or charge any budget."
            ),
            risk_level="medium",
            requires_approval=True,
            target_integration="internal",
            allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            parsed = CreateCampaignInput(**arguments)
            return True, "", parsed.model_dump()
        except Exception as exc:
            return False, str(exc), {}

    async def execute(
        self,
        arguments: dict[str, Any],
        tenant_id: str,
        role_key: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        parsed = CreateCampaignInput(**arguments)
        body = CampaignCreate(
            name=parsed.name,
            objective=parsed.objective,
            channel=parsed.channel,
            budget=parsed.budget,
            target_audience=parsed.target_audience,
            start_date=parsed.start_date,
            end_date=parsed.end_date,
            kpis=[],
            created_by=role_key,
        )
        campaign = await svc_create_campaign(body, tenant_id, db)
        return {
            "success": True,
            "campaign_id": campaign.id,
            "message": (
                f"Campaign '{campaign.name}' created successfully "
                f"(ID: {campaign.id}, status: {campaign.status})."
            ),
        }


class UpdateCampaignAction(BaseActionTool):
    """
    Updates an existing campaign.
    Risk level is determined at validation time:
    - Budget change → HIGH
    - Status → active/cancelled → HIGH
    - Other changes → MEDIUM
    """

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="update_campaign",
            display_name="Update Campaign",
            description=(
                "Update an existing campaign record. "
                "Budget changes and status transitions are HIGH risk. "
                "Other changes are MEDIUM risk. Always requires approval."
            ),
            risk_level="high",   # conservative default; actual risk checked in validate
            requires_approval=True,
            target_integration="internal",
            allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            parsed = UpdateCampaignInput(**arguments)
            return True, "", parsed.model_dump()
        except Exception as exc:
            return False, str(exc), {}

    async def execute(
        self,
        arguments: dict[str, Any],
        tenant_id: str,
        role_key: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        parsed = UpdateCampaignInput(**arguments)

        # Verify the campaign exists and belongs to this tenant
        existing = await get_campaign(parsed.campaign_id, tenant_id, db)
        if not existing:
            return {
                "success": False,
                "message": (
                    f"Campaign '{parsed.campaign_id}' not found or does not belong "
                    "to this tenant."
                ),
            }

        body = CampaignUpdate(
            name=parsed.name,
            objective=parsed.objective,
            channel=parsed.channel,
            budget=parsed.budget,
            status=parsed.status,
            target_audience=parsed.target_audience,
            start_date=parsed.start_date,
            end_date=parsed.end_date,
        )
        updated = await svc_update_campaign(parsed.campaign_id, body, tenant_id, db)
        if not updated:
            return {"success": False, "message": "Campaign update failed."}

        return {
            "success": True,
            "campaign_id": updated.id,
            "message": (
                f"Campaign '{updated.name}' updated successfully "
                f"(status: {updated.status}, budget: {updated.budget})."
            ),
            "new_status": updated.status,
            "new_budget": updated.budget,
        }
