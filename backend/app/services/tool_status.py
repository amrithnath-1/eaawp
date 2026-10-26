"""
What the selected AI employee can actually do right now, from server state only (no fixed numbers):

* built-in tools from the role's saved configuration, each checked against the tool registries;
* integration tools from capability grants, each checked against the integration's live connection state and the
  execution rules (HIGH-risk integration capabilities are never run by an AI employee);
* pending approvals and recent operations (execution plans) by status.

The statuses are the same rules the execution path applies, so the screen and the behaviour cannot disagree.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import is_admin_user
from app.db.models import ApprovalRequest, ExecutionPlan, User

STATUS_LABELS = {
    "available": "Ready to use",
    "requires_approval": "Runs only after human approval",
    "disabled": "Turned off in this AI employee's configuration",
    "not_implemented": "Configured but not available in this version",
    "integration_not_connected": "Its integration is not connected",
    "integration_disabled": "Its integration is switched off",
    "blocked_high_risk": "High-risk integration action: not run by AI employees",
    "capability_missing": "The provider no longer offers this capability",
}
OPERATION_WINDOW_DAYS = 30


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    for stop in (". ", "\n"):
        if stop in text:
            text = text.split(stop, 1)[0] + "."
            break
    return text[:240]


def _builtin_description(key: str) -> str:
    from app.actions.registry import get_action_tool
    from app.tools.registry import MASTER_TOOL_REGISTRY

    action = get_action_tool(key)
    if action is not None:
        return _first_sentence(action.meta.description)
    tool = MASTER_TOOL_REGISTRY.get(key)
    return _first_sentence(getattr(tool, "description", "") or "") if tool is not None else ""


def _builtin_tools(scopes: list[dict]) -> list[dict]:
    from app.actions.registry import get_action_tool, is_action_tool
    from app.tools.registry import MASTER_TOOL_REGISTRY

    out = []
    for s in scopes:
        key = s["tool_key"]
        registered = key in MASTER_TOOL_REGISTRY or get_action_tool(key) is not None
        gov = s["governance"]
        if gov == "disabled":
            status = "disabled"
        elif not registered:
            status = "not_implemented"
        elif gov == "requires_approval":
            status = "requires_approval"
        else:
            action = get_action_tool(key)
            status = "requires_approval" if action is not None and (
                action.meta.requires_approval or action.meta.risk_level == "high") else "available"
        out.append({
            "key": key, "name": s["name"], "source": "built_in",
            "kind": "action" if is_action_tool(key) else "read",
            "description": _builtin_description(key),
            "status": status, "status_label": STATUS_LABELS[status],
        })
    return out


async def _integration_tools(db: AsyncSession, tenant_id: str, role_key: str) -> list[dict]:
    from app.db.integration_models import CapabilityGrant, Integration
    from app.integrations.integration_registry import integration_registry
    from app.integrations.provider import CapabilityCategory

    rows = (await db.execute(
        select(CapabilityGrant, Integration)
        .join(Integration, Integration.id == CapabilityGrant.integration_id)
        .where(CapabilityGrant.tenant_id == tenant_id, Integration.tenant_id == tenant_id,
               CapabilityGrant.role_key == role_key, CapabilityGrant.is_granted == True)  # noqa: E712
        .order_by(Integration.display_name, CapabilityGrant.capability_key)
    )).all()
    out = []
    for grant, integ in rows:
        provider = integration_registry.get(integ.provider_type)
        cap = provider.get_capability(grant.capability_key) if provider else None
        if cap is None:
            status, name, desc, risk, kind = "capability_missing", grant.capability_key, "", None, "read"
        else:
            name, desc, risk = cap.display_name, _first_sentence(cap.description), cap.risk_level.value
            kind = "read" if cap.category in (CapabilityCategory.READ, CapabilityCategory.ANALYTICS) else "action"
            if integ.status != "connected":
                status = "integration_not_connected"
            elif not integ.is_enabled:
                status = "integration_disabled"
            elif risk == "high":
                status = "blocked_high_risk"
            else:
                status = "available"
        out.append({
            "key": grant.capability_key, "name": name, "source": "integration", "kind": kind,
            "description": desc, "risk_level": risk,
            "integration": {"id": integ.id, "provider_type": integ.provider_type, "name": integ.display_name,
                            "status": integ.status, "enabled": bool(integ.is_enabled)},
            "status": status, "status_label": STATUS_LABELS[status],
        })
    return out


async def _operations(db: AsyncSession, user: User, role_key: str) -> dict:
    """Execution plans of this AI employee in the last 30 days, by status. Employees see only their own."""
    from app.db.conversation_models import Conversation

    since = datetime.now(timezone.utc) - timedelta(days=OPERATION_WINDOW_DAYS)
    stmt = (select(ExecutionPlan.status, func.count())
            .where(ExecutionPlan.tenant_id == user.tenant_id, ExecutionPlan.role_key == role_key,
                   ExecutionPlan.created_at >= since))
    if not is_admin_user(user):
        own = select(Conversation.id).where(Conversation.tenant_id == user.tenant_id, Conversation.user_id == user.id)
        stmt = stmt.where(ExecutionPlan.session_id.in_(own))
    counts = dict((await db.execute(stmt.group_by(ExecutionPlan.status))).all())
    return {
        "window_days": OPERATION_WINDOW_DAYS,
        "scope": "company" if is_admin_user(user) else "mine",
        "running": int(counts.get("running", 0) + counts.get("planning", 0)),
        "awaiting_approval": int(counts.get("awaiting_approval", 0)),
        "completed": int(counts.get("completed", 0)),
        "failed": int(counts.get("failed", 0)),
        "cancelled": int(counts.get("rejected", 0) + counts.get("cancelled", 0)),
    }


async def tool_status(db: AsyncSession, user: User) -> dict:
    from app.services.workspaces import _role_tools, _selection, get_workspace

    sel = await _selection(db, user)
    if sel is None:
        return {"role_key": None, "tools": [], "counts": {}, "approvals": {}, "operations": {}}
    role_key = sel.role_key
    scopes, *_ = await _role_tools(db, user.tenant_id, role_key)
    tools = _builtin_tools(scopes) + await _integration_tools(db, user.tenant_id, role_key)
    pending = (await db.execute(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.tenant_id == user.tenant_id, ApprovalRequest.status == "pending"))).scalar_one()
    w = get_workspace(role_key)
    return {
        "role_key": role_key,
        "role_name": w.name if w else role_key,
        "tools": tools,
        "counts": {
            "total": len(tools),
            "available": sum(t["status"] == "available" for t in tools),
            "requires_approval": sum(t["status"] == "requires_approval" for t in tools),
            "blocked": sum(t["status"] not in ("available", "requires_approval") for t in tools),
            "integration_available": sum(t["source"] == "integration" and t["status"] == "available" for t in tools),
        },
        "approvals": {"pending": int(pending), "can_decide": is_admin_user(user)},
        "operations": await _operations(db, user, role_key),
    }
