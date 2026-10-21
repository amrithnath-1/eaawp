"""
Medical Assistant action tool (internal records only).

  update_appointment_status   MEDIUM  confirm / reschedule / complete / cancel an appointment; ALWAYS requires human approval
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.services import medical_service as ms


class UpdateAppointmentInput(BaseModel):
    appointment_id: str = Field(..., min_length=1, max_length=36)
    status: Literal["confirmed", "completed", "no_show", "cancelled"]
    scheduled_for: str | None = Field(default=None, max_length=25)
    clinician_name: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)


class UpdateAppointmentStatusAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="update_appointment_status", display_name="Update Appointment Status",
            description="Confirm, reschedule, complete or cancel an appointment. Requires human approval. Does not give medical advice.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=["MEDICAL_ASSISTANT"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            return True, "", UpdateAppointmentInput(**arguments).model_dump()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        p = UpdateAppointmentInput(**arguments)
        a = await ms.get(db, tenant_id, p.appointment_id)
        if a is None:
            return {"success": False, "message": "Appointment not found."}
        label = f"{role_key} (AI)"
        actor = SimpleNamespace(id=f"agent:{role_key}"[:36], email=label, name=label)
        try:
            ms.set_status(db, a, p.status, actor, p.scheduled_for, p.clinician_name, p.note)
        except ms.MedicalError as exc:
            return {"success": False, "message": str(exc)}
        await db.flush()
        return {"success": True, "appointment_id": a.id, "message": f"Appointment is now {a.status.replace('_', ' ')}."}
