"""
EAAWP Action Tool Registry

The single source of truth for all registered action tools.
Action tools are distinct from read-only query tools in MASTER_TOOL_REGISTRY.

Adding a new action tool:
1. Create a class in app/actions/<tool_name>.py that extends BaseActionTool.
2. Register it here.
3. Add its key to the relevant RoleConfig.toolScopes.
"""

from __future__ import annotations

from app.actions.base import BaseActionTool
from app.actions.campaign_actions import CreateCampaignAction, UpdateCampaignAction
from app.actions.create_internal_task import CreateInternalTaskAction
from app.actions.draft_email import DraftEmailAction
from app.actions.send_email import SendEmailAction
from app.actions.strategy_actions import CreateMarketingObjectiveAction, UpdateMarketingObjectiveAction

# Registry maps tool_name → BaseActionTool instance
ACTION_REGISTRY: dict[str, BaseActionTool] = {
    "create_internal_task": CreateInternalTaskAction(),
    "draft_email": DraftEmailAction(),
    "send_email": SendEmailAction(),
    "create_campaign": CreateCampaignAction(),
    "update_campaign": UpdateCampaignAction(),
    "create_marketing_objective": CreateMarketingObjectiveAction(),
    "update_marketing_objective": UpdateMarketingObjectiveAction(),
}


def get_action_tool(tool_name: str) -> BaseActionTool | None:
    """Return the action tool for the given name, or None if not registered."""
    return ACTION_REGISTRY.get(tool_name)


def is_action_tool(tool_name: str) -> bool:
    """Return True if the tool_name refers to an action tool (not a read tool)."""
    return tool_name in ACTION_REGISTRY
