"""
EAAWP Marketing Strategy Action Tools

create_marketing_objective — MEDIUM risk, requires approval
update_marketing_objective — HIGH risk when priority/target changes
"""
from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.actions.base import ActionToolMeta, BaseActionTool
from app.schemas.strategy import CreateObjectiveInput, ObjectiveUpdate, UpdateObjectiveInput
from app.services.strategy_service import create_objective, update_objective


class CreateMarketingObjectiveAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="create_marketing_objective",
            display_name="Create Marketing Objective",
            description="Create a new strategic marketing objective. MEDIUM risk — requires approval.",
            risk_level="medium", requires_approval=True,
            target_integration="internal", allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            parsed = CreateObjectiveInput(**arguments)
            return True, "", parsed.model_dump()
        except Exception as exc:
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        parsed = CreateObjectiveInput(**arguments)
        body = CreateObjectiveInput(**parsed.model_dump())
        body.created_by = role_key
        obj = await create_objective(body, tenant_id, db)
        return {
            "success": True, "objective_id": obj.id,
            "message": f"Marketing objective '{obj.name}' created (status: {obj.status}).",
        }


class UpdateMarketingObjectiveAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="update_marketing_objective",
            display_name="Update Marketing Objective",
            description="Update a marketing objective. HIGH risk — requires approval.",
            risk_level="high", requires_approval=True,
            target_integration="internal", allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            parsed = UpdateObjectiveInput(**arguments)
            return True, "", parsed.model_dump()
        except Exception as exc:
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        parsed = UpdateObjectiveInput(**arguments)
        body = ObjectiveUpdate(
            name=parsed.name, priority=parsed.priority, status=parsed.status,
            target_value=parsed.target_value, current_value=parsed.current_value,
        )
        updated = await update_objective(parsed.objective_id, body, tenant_id, db)
        if not updated:
            return {"success": False, "message": "Objective not found or wrong tenant."}
        return {
            "success": True, "objective_id": updated.id,
            "message": f"Objective '{updated.name}' updated (status: {updated.status}).",
        }
