"""
Institutional Clerk action tools (internal records only; no external side effects).

  draft_service_document   LOW    creates a DRAFT document (not visible to requesters, never issued by the agent)
  update_service_request   MEDIUM changes a request's status / adds a note; ALWAYS requires human approval
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.base import ActionToolMeta, BaseActionTool
from app.db.clerk_models import IssuedDocument
from app.services import clerk_service as cs

MAX_DRAFTS = 200


class DraftDocumentInput(BaseModel):
    template_key: Literal["bonafide", "leave_approval", "notice", "general_letter"]
    fields: dict[str, str] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=36)


class UpdateRequestInput(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=36)
    status: Literal["in_review", "needs_info", "approved", "rejected", "fulfilled"]
    note: str = Field(default="", max_length=2000)


def agent_actor(role_key: str) -> SimpleNamespace:
    label = f"{role_key} (AI)"
    return SimpleNamespace(id=f"agent:{role_key}"[:36], email=label, name=label)


class DraftServiceDocumentAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="draft_service_document", display_name="Draft Service Document",
            description="Prepare a DRAFT letter/certificate/notice from a template. Drafts are only visible to administrators "
                        "and are issued (numbered) by a human. No external effect.",
            risk_level="low", requires_approval=False, target_integration="internal", allowed_roles=["INSTITUTIONAL_CLERK"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            return True, "", DraftDocumentInput(**arguments).model_dump()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        p = DraftDocumentInput(**arguments)
        n = (await db.execute(select(func.count()).select_from(IssuedDocument).where(
            IssuedDocument.tenant_id == tenant_id, IssuedDocument.status == "draft"))).scalar_one()
        if n >= MAX_DRAFTS:
            return {"success": False, "message": f"There are already {MAX_DRAFTS} draft documents; an administrator should issue or void some."}
        req = None
        if p.request_id:
            req = await cs.get_request(db, tenant_id, p.request_id)
            if req is None:
                return {"success": False, "message": "Request not found."}
        try:
            doc = await cs.draft_document(db, tenant_id, p.template_key, p.fields, f"{role_key} (AI)", req)
        except cs.ClerkError as exc:
            return {"success": False, "message": str(exc)}
        await db.flush()
        return {"success": True, "document_id": doc.id, "message": f"Draft '{doc.title}' prepared for administrator review (not issued)."}


class UpdateServiceRequestAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name="update_service_request", display_name="Update Service Request",
            description="Change a service request's status (with a note). Requires human approval.",
            risk_level="medium", requires_approval=True, target_integration="internal", allowed_roles=["INSTITUTIONAL_CLERK"],
        )

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        try:
            return True, "", UpdateRequestInput(**arguments).model_dump()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), {}

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: AsyncSession) -> dict[str, Any]:
        p = UpdateRequestInput(**arguments)
        req = await cs.get_request(db, tenant_id, p.request_id)
        if req is None:
            return {"success": False, "message": "Request not found."}
        try:
            cs.change_status(db, req, p.status, agent_actor(role_key), p.note)
        except cs.ClerkError as exc:
            return {"success": False, "message": str(exc)}
        await db.flush()
        return {"success": True, "request_id": req.id, "message": f"Request '{req.title}' is now {req.status.replace('_', ' ')}."}
