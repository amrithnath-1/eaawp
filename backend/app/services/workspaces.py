"""
AI employee workspaces: which role a person works with, and what that role's workspace contains.

A workspace is the person's chosen AI employee (one of the four built-in roles). It decides the navigation, the
dashboard, the quick prompts and the role whose server-side configuration (persona, tools, knowledge scope, safety
rules) the AI Core runs with. It is a VIEW, not a permission: everything it shows is still enforced per request by the
existing gates (company module activation, admin-only routes, per-record access, capability grants). Choosing a
workspace can never unlock a disabled module or an admin feature. Switching never deletes or moves any data.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import is_admin_user
from app.db.models import AuditLog, RoleConfiguration, User
from app.db.workspace_models import UserWorkspace
from app.services import modules as ms


@dataclass(frozen=True)
class WorkspaceDef:
    key: str
    name: str
    purpose: str
    capabilities: tuple[str, ...]
    knowledge_domain: str
    nav: tuple[str, ...]                 # navigation entries specific to this role (route names without "/")
    safety_rules: tuple[str, ...]


# Shown in every workspace. Each page still enforces its own access rules on the server.
COMMON_NAV: tuple[str, ...] = ("cabin", "workspace", "approvals", "messages", "library", "workflows", "activity", "settings")
# Company administration; listed only for administrators (the API refuses everyone else regardless).
ADMIN_NAV: tuple[str, ...] = ("team", "employees", "marketplace", "integrations", "connections", "meeting", "audit")

_COMMON_SAFETY = (
    "Acts only for the signed-in person's own company; tenant and identity come from the verified sign-in.",
    "Uses only the tools the company granted this role; actions that change or send anything need human approval.",
    "Answers from company knowledge and connected data and says when it does not know.",
)

WORKSPACES: tuple[WorkspaceDef, ...] = (
    WorkspaceDef(
        "DIGITAL_MARKETING_MANAGER", "Digital Marketing Manager",
        "Plans and analyses marketing: campaigns, SEO, content and performance reporting.",
        ("Campaign planning and performance analysis", "SEO insights from Google Search Console",
         "Traffic analysis from Google Analytics", "Content briefs, ideas and drafts", "Marketing reports"),
        "Marketing: campaigns, content, brand and SEO documents, plus authorized Google Analytics / Search Console data.",
        ("customize", "integrations", "scheduled", "meeting"),
        ("Never sends external communications (email, social) without explicit human approval.",
         "Google data is read only through integrations an administrator authorized."),
    ),
    WorkspaceDef(
        "INSTITUTIONAL_CLERK", "Institutional Clerk",
        "Processes institutional paperwork: service requests, records and official documents for approval.",
        ("Service request intake and tracking", "Draft certificates and letters from approved templates",
         "Extract details from uploaded documents", "Approval workflow for status changes and issuing"),
        "Institutional policies, procedures and templates; each person sees only the requests they may see.",
        ("clerk", "scheduled"),
        ("Prepares drafts only; a human approves and issues every document.",
         "Never discloses one person's request to another; conversations are not stored in shared memory."),
    ),
    WorkspaceDef(
        "MEDICAL_ASSISTANT", "Medical Assistant",
        "Supports clinic administration: appointment requests, clinic information and intake organisation.",
        ("Appointment requests and staff queue", "Clinic hours, location and preparation answers",
         "Intake summaries in the patient's own words", "Emergency wording detection before any AI is used"),
        "Clinic information documents only; patient records are visible only to the patient and clinic staff.",
        ("clinic",),
        ("Not a clinician: never diagnoses, interprets symptoms or advises on medicines or treatment.",
         "Emergencies are directed to emergency services by a deterministic check before the model runs.",
         "No autonomous clinical decisions; every status change needs staff approval; nothing is kept in shared memory."),
    ),
    WorkspaceDef(
        "DATA_INTELLIGENCE_ANALYST", "Data Analyst",
        "Explores company data: dataset uploads, database connections, analysis, charts and reports.",
        ("Dataset upload and exploration", "Deterministic analysis: summaries, groups, trends, comparisons",
         "Charts and saved reports with CSV export", "Read-only database queries through approved mappings"),
        "Uploaded datasets and authorized database connections, with blocked columns and restricted datasets enforced.",
        ("data", "scheduled"),
        ("Reports only numbers the analysis engine computed and always names the dataset.",
         "Database access is read only, through admin-defined mappings and entity permissions, and audited."),
    ),
)
_BY_KEY = {w.key: w for w in WORKSPACES}
WORKSPACE_KEYS = frozenset(_BY_KEY)


def get_workspace(key: str) -> WorkspaceDef | None:
    return _BY_KEY.get(key)


def navigation_for(key: str, user: User) -> list[str]:
    """Ordered, de-duplicated navigation for this role and person."""
    w = _BY_KEY[key]
    items = list(COMMON_NAV[:2]) + list(w.nav) + list(COMMON_NAV[2:])
    if is_admin_user(user):
        items += list(ADMIN_NAV)
    return list(dict.fromkeys(items))


async def availability(db: AsyncSession, user: User, key: str) -> str | None:
    """None when this person may work in the workspace now, else the reason they cannot."""
    w = _BY_KEY.get(key)
    if w is None:
        return "This AI employee does not exist."
    if not await ms.is_module_active(db, user.tenant_id, key):
        return f"The {w.name} module is not activated for your company. A company administrator can activate it from the Marketplace."
    from app.services.employee_lifecycle import employee_is_blocked
    if await employee_is_blocked(db, user.tenant_id, key):
        return f"The {w.name} AI employee is paused. An administrator can resume it from the Employees page."
    return None


async def _role_tools(db: AsyncSession, tenant_id: str, key: str) -> tuple[list[dict], list[str], list[str], str, str, list[str]]:
    """The company's own configuration for the role when it has one (read only: GET never seeds), else the defaults."""
    from app.api.routers.role_config import _get_defaults, _orm_to_schema

    row = (await db.execute(select(RoleConfiguration).where(
        RoleConfiguration.tenant_id == tenant_id, RoleConfiguration.role_key == key))).scalar_one_or_none()
    if row is not None:
        cfg = _orm_to_schema(row)
        scopes = [{"name": s.name, "tool_key": s.tool_key, "governance": s.governance} for s in cfg.tool_scopes]
        return scopes, list(cfg.allowed_tools), list(cfg.guarded_tools), cfg.role_name, cfg.agent_name, list(cfg.quick_prompts)
    d = _get_defaults(key)
    scopes = [{"name": s["name"], "tool_key": s["tool_key"], "governance": s["governance"]} for s in json.loads(d["tool_scopes_json"])]
    allowed = [s["tool_key"] for s in scopes if s["governance"] == "enabled"]
    guarded = [s["tool_key"] for s in scopes if s["governance"] == "requires_approval"]
    return scopes, allowed, guarded, d["role_name"], d["agent_name"], json.loads(d["quick_prompts_json"])


async def _selection(db: AsyncSession, user: User) -> UserWorkspace | None:
    return (await db.execute(select(UserWorkspace).where(
        UserWorkspace.user_id == user.id, UserWorkspace.tenant_id == user.tenant_id))).scalar_one_or_none()


async def workspace_state(db: AsyncSession, user: User) -> dict:
    roles = []
    for w in WORKSPACES:
        scopes, *_ = await _role_tools(db, user.tenant_id, w.key)
        reason = await availability(db, user, w.key)
        roles.append({
            "key": w.key, "name": w.name, "purpose": w.purpose, "capabilities": list(w.capabilities),
            "knowledge_domain": w.knowledge_domain,
            "main_tools": [{"name": s["name"], "requires_approval": s["governance"] == "requires_approval"}
                           for s in scopes if s["governance"] != "disabled"],
            "available": reason is None, "unavailable_reason": reason,
        })

    row = await _selection(db, user)
    selected = None
    notice = None
    if row is not None:
        reason = next((r["unavailable_reason"] for r in roles if r["key"] == row.role_key),
                      "This AI employee is no longer offered.")
        if reason is None:
            selected = row
        else:
            w = _BY_KEY.get(row.role_key)
            notice = f"Your previous workspace ({w.name if w else row.role_key}) is not available: {reason} Choose another AI employee."

    out: dict = {
        "needs_selection": selected is None,
        "notice": notice,
        "can_switch": sum(1 for r in roles if r["available"]) > 1,
        "roles": roles,
        "selected": None,
        "navigation": [],
        "ai": None,
    }
    if selected is not None:
        w = _BY_KEY[selected.role_key]
        scopes, allowed, guarded, role_name, agent_name, prompts = await _role_tools(db, user.tenant_id, w.key)
        out["selected"] = {"role_key": w.key, "name": w.name, "source": selected.source, "selected_at": selected.selected_at}
        out["navigation"] = navigation_for(w.key, user)
        out["ai"] = {
            "role_key": w.key, "role_name": role_name, "agent_name": agent_name,
            "allowed_tools": allowed, "guarded_tools": guarded, "quick_prompts": prompts,
            "knowledge_scope": w.key, "knowledge_domain": w.knowledge_domain,
            "safety_rules": list(_COMMON_SAFETY + w.safety_rules),
        }
    return out


async def select_workspace(db: AsyncSession, user: User, key: str) -> dict:
    if key not in WORKSPACE_KEYS:
        raise HTTPException(status_code=404, detail="This AI employee does not exist.")
    reason = await availability(db, user, key)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)

    row = await _selection(db, user)
    previous = row.role_key if row is not None else None
    if row is None:
        row = UserWorkspace(id=str(uuid.uuid4()), tenant_id=user.tenant_id, user_id=user.id, role_key=key, source="user")
        db.add(row)
    elif row.role_key != key or row.source != "user":
        from datetime import datetime, timezone
        row.role_key, row.source, row.selected_at = key, "user", datetime.now(timezone.utc)

    # Configure the role for the company from the existing defaults if it never ran before (same as first use).
    from app.api.routers.role_config import _get_or_seed
    await _get_or_seed(key, user.tenant_id, db)

    if previous != key:
        name = _BY_KEY[key].name
        event = f"workspace selected: {name}" if previous is None else f"workspace switched from {_BY_KEY[previous].name if previous in _BY_KEY else previous} to {name}"
        db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=user.tenant_id, actor=str(user.id)[:64], event=event[:500],
                        department="workspace", status="ok"))
    await db.flush()
    return await workspace_state(db, user)
