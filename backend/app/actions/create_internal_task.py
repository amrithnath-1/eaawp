"""
EAAWP create_internal_task Action

The single safe internal action used to validate the complete action framework.

What it does:
- Creates an EAAWP-internal Task record in the EAAWP database ONLY.

What it does NOT do:
- Does NOT send emails.
- Does NOT publish content to external platforms.
- Does NOT call external marketing APIs.
- Does NOT modify any company external database.
- Does NOT execute arbitrary code.

Risk level: LOW — may execute automatically when role config allows.
Default approval: not required (administrator may override in role config).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.db.models import AIEmployee, Task
from app.schemas.actions import CreateInternalTaskInput


class CreateInternalTaskAction(BaseActionTool):
    """
    Creates an EAAWP internal task record.
    This is the reference implementation of the action tool framework.
    """

    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="create_internal_task",
            display_name="Create Internal Task",
            description=(
                "Creates an internal EAAWP task record for the Digital Marketing Manager. "
                "This action only creates a task within the EAAWP platform — "
                "it does not send emails, publish content, or call external systems."
            ),
            risk_level="low",
            requires_approval=False,   # low risk — auto-execute if role allows
            target_integration="internal",
            allowed_roles=["DIGITAL_MARKETING_MANAGER"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Validate and normalise arguments using Pydantic schema."""
        try:
            parsed = CreateInternalTaskInput(**arguments)
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
        """
        Create the Task record. Returns success metadata.
        Never returns credentials or raw data from external systems.
        """
        # Parse validated arguments
        parsed = CreateInternalTaskInput(**arguments)

        # Find or use a placeholder AI employee ID for this tenant/role
        ai_emp_result = await db.execute(
            select(AIEmployee).where(
                AIEmployee.tenant_id == tenant_id,
                AIEmployee.role_key == role_key,
                AIEmployee.is_active == True,  # noqa: E712
            ).limit(1)
        )
        ai_emp = ai_emp_result.scalar_one_or_none()

        # If no AIEmployee exists, use a placeholder ID for the task
        # (In production this would require a real AIEmployee record)
        ai_employee_id = ai_emp.id if ai_emp else f"placeholder-{tenant_id[:8]}"

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        task = Task(
            id=task_id,
            tenant_id=tenant_id,
            ai_employee_id=ai_employee_id,
            name=parsed.title,
            goal=parsed.description,
            status="running",
            progress=0,
            department=parsed.department,
            steps_json="[]",
            sources_json="[]",
            started_at=now,
        )
        db.add(task)
        await db.flush()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Internal task '{parsed.title}' created successfully.",
            "priority": parsed.priority,
            "department": parsed.department,
        }
