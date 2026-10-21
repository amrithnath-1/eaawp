"""
Task readiness: can this request run with real data yet, and if not, what
exactly is missing?

Used by the execution router BEFORE planning.  When a request needs an
integration that is not set up (Google OAuth credentials, an authorised
connection, or the role's read grant), the request is saved as a PendingTask,
the user gets a truthful "setup needed" reply, and the task is resumed once
setup is complete.  The model is never asked to answer such a request from
memory.

Detection is deterministic (keywords), not an LLM call, so it works when the
LLM is rate-limited and cannot be talked out of a requirement.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.integration_models import CapabilityGrant, Integration
from app.db.models import SemanticMapping
from app.db.pending_task_models import PendingTask
from app.integrations.integration_registry import integration_registry
from app.integrations.provider import CapabilityCategory, RiskLevel
from app.services.provider_config_service import get_provider_configuration_status

State = Literal["ready", "needs_configuration", "needs_authorization", "needs_grant", "needs_property"]


@dataclass(frozen=True)
class Requirement:
    provider_type: str
    capabilities: tuple[str, ...]
    purpose: str
    roles: tuple[str, ...] = ()   # roles this gate applies to (empty = all)
    needs_property: bool = False  # an admin must have selected which property to read


GA4_TRAFFIC = Requirement(
    provider_type="google_analytics",
    capabilities=("run_report",),
    purpose="read website traffic reports from Google Analytics 4",
    roles=("DIGITAL_MARKETING_MANAGER",),
)

GSC_SEO = Requirement(
    provider_type="google_search_console",
    capabilities=("get_search_analytics",),
    purpose="read search performance (clicks, impressions, CTR, position) from Google Search Console",
    roles=("DIGITAL_MARKETING_MANAGER",),
    needs_property=True,
)

# An explicit mention of Search Console is always a Search Console request.
_GSC_EXPLICIT = re.compile(r"\b(google )?search console\b|\bgsc\b", re.I)
# Vocabulary that only exists in search performance data (bare "clicks"/"ctr" are
# too generic - ads and email use them too).
_GSC_SEO = re.compile(
    r"\bsearch impressions?\b|\b(organic|search)\b[^.?!]{0,40}\b(clicks|impressions)\b"
    r"|\b(clicks|impressions)\b[^.?!]{0,40}\b(from|in|on) (organic|google) search\b"
    r"|\baverage (search )?position\b|\bavg\.? position\b"
    r"|\b(search|top|ranking|organic)\s+(quer(y|ies)|keywords?)\b|\btop\s+(pages|queries|keywords)\b"
    r"|\bkeyword (rankings?|positions?|performance)\b|\b(organic )?search (performance|rankings?|visibility)\b"
    r"|\bwhat (do|did) (people|users) search\b",
    re.I,
)

# An explicit mention of Google Analytics always means GA.
_GA_EXPLICIT = re.compile(r"\b(google analytics|ga4|ga data|analytics (data|report|property))\b", re.I)
# Traffic vocabulary means GA unless the company already has its own mapped data.
_GA_TRAFFIC = re.compile(
    r"\b(web(site)?|site|organic|paid|referral)\s+traffic\b|\btraffic\s+(sources?|channels?|by)\b"
    r"|\bsessions?\b|\b(unique\s+|new\s+)?visitors?\b|\bbounce rate\b|\bpage ?views?\b"
    r"|\bchannels?\s+(drove|bring|brought)\b",
    re.I,
)


@dataclass
class Assessment:
    state: State
    requirement: Requirement
    missing_fields: list[str] = field(default_factory=list)
    redirect_uri: str = ""
    integration_id: str | None = None
    missing_capabilities: list[str] = field(default_factory=list)
    properties: list[dict] = field(default_factory=list)   # choices for needs_property

    @property
    def ready(self) -> bool:
        return self.state == "ready"


async def _has_company_data_mappings(tenant_id: str, db: AsyncSession) -> bool:
    row = await db.execute(
        select(SemanticMapping.id).where(SemanticMapping.tenant_id == tenant_id).limit(1)
    )
    return row.first() is not None


async def detect_requirements(
    prompt: str, tenant_id: str, role_key: str, db: AsyncSession
) -> list[Requirement]:
    """Every integration this request needs, most specific first."""
    text = prompt or ""
    found: list[Requirement] = []
    if _GSC_EXPLICIT.search(text) or _GSC_SEO.search(text):
        found.append(GSC_SEO)
    if _GA_EXPLICIT.search(text):
        found.append(GA4_TRAFFIC)
    elif _GA_TRAFFIC.search(text) and not found and not await _has_company_data_mappings(tenant_id, db):
        found.append(GA4_TRAFFIC)
    return [r for r in found if not r.roles or role_key in r.roles]


async def detect_requirement(
    prompt: str, tenant_id: str, role_key: str, db: AsyncSession
) -> Requirement | None:
    """The first integration this request needs, or None."""
    found = await detect_requirements(prompt, tenant_id, role_key, db)
    return found[0] if found else None


async def first_unmet(
    prompt: str, tenant_id: str, role_key: str, db: AsyncSession
) -> "Assessment | None":
    """The first requirement of this request that is not ready, or None when all are."""
    for req in await detect_requirements(prompt, tenant_id, role_key, db):
        a = await assess(req, tenant_id, role_key, db)
        if not a.ready:
            return a
    return None


async def assess(req: Requirement, tenant_id: str, role_key: str, db: AsyncSession) -> Assessment:
    """Check, in order: a connected integration, the role's grants, then OAuth client config."""
    rows = await db.execute(
        select(Integration)
        .where(
            Integration.tenant_id == tenant_id,
            Integration.provider_type == req.provider_type,
            Integration.status == "connected",
            Integration.is_enabled == True,  # noqa: E712
        )
        .order_by(Integration.created_at.desc())
    )
    connected = list(rows.scalars().all())

    best: Assessment | None = None
    for integ in connected:
        grants = await db.execute(
            select(CapabilityGrant.capability_key).where(
                CapabilityGrant.tenant_id == tenant_id,
                CapabilityGrant.integration_id == integ.id,
                CapabilityGrant.role_key == role_key,
                CapabilityGrant.is_granted == True,  # noqa: E712
            )
        )
        have = {g for (g,) in grants.all()}
        missing = [c for c in req.capabilities if c not in have]
        if not missing:
            if req.needs_property:
                return await _check_property(req, integ, tenant_id, db)
            return Assessment("ready", req, integration_id=integ.id)
        best = best or Assessment(
            "needs_grant", req, integration_id=integ.id, missing_capabilities=missing
        )
    if best:
        return best

    cfg = await get_provider_configuration_status(req.provider_type, tenant_id, db)
    if cfg.state != "CONFIGURED":
        return Assessment(
            "needs_configuration", req,
            missing_fields=list(cfg.missing_fields), redirect_uri=cfg.redirect_uri,
        )
    return Assessment("needs_authorization", req, redirect_uri=cfg.redirect_uri)


async def _check_property(
    req: Requirement, integ: Integration, tenant_id: str, db: AsyncSession
) -> Assessment:
    """
    A property must be chosen before reading data.  An admin's stored choice wins;
    a single accessible property is selected automatically; several need a choice.
    If they cannot be listed, the task proceeds and the real error is reported.
    """
    from app.integrations import manager

    if manager.default_property_of(integ):
        return Assessment("ready", req, integration_id=integ.id)
    try:
        props = await manager.list_selectable_properties(integ.id, tenant_id, db)
    except Exception:
        return Assessment("ready", req, integration_id=integ.id)
    if len(props) == 1:
        await manager.set_default_property(integ.id, tenant_id, props[0]["id"], db)
        return Assessment("ready", req, integration_id=integ.id)
    if len(props) > 1:
        return Assessment("needs_property", req, integration_id=integ.id, properties=props[:50])
    return Assessment("ready", req, integration_id=integ.id)


def _provider_name(provider_type: str) -> str:
    p = integration_registry.get(provider_type)
    return p.display_name if p else provider_type


def setup_message(a: Assessment, *, is_admin: bool) -> tuple[str, str, dict]:
    """(reply, next_action, action_data) - never contains a credential value."""
    name = _provider_name(a.requirement.provider_type)
    saved = "I’ve saved your request and will not guess at numbers. "
    data = {"provider_type": a.requirement.provider_type}
    if a.state == "needs_configuration":
        data.update(missing_fields=a.missing_fields, redirect_uri=a.redirect_uri)
        if is_admin:
            return (
                f"{saved}To read {name} data, Google OAuth credentials for your company must be "
                "entered first. Use the secure form below; the secret is stored encrypted and never shown again.",
                "CONFIGURATION_REQUIRED", data,
            )
        return (
            f"{saved}{name} is not set up for your company yet. An administrator needs to add the "
            "Google OAuth credentials and connect it. I’ll be ready to run this once they have.",
            "ADMIN_REQUIRED", data,
        )
    if a.state == "needs_authorization":
        if is_admin:
            return (
                f"{saved}{name} is not connected yet. Authorise it with Google (read-only access) "
                "and I’ll pick this request back up.",
                "REDIRECT_TO_OAUTH", data,
            )
        return (
            f"{saved}{name} is not connected yet. An administrator needs to authorise it with "
            "Google (read-only). I’ll be ready to run this once they have.",
            "ADMIN_REQUIRED", data,
        )
    if a.state == "needs_property":
        data.update(integration_id=a.integration_id, properties=a.properties)
        if is_admin:
            return (
                f"{saved}{name} has access to several properties. Choose which one this AI employee "
                "should report on and I’ll run the request.",
                "SELECT_PROPERTY", data,
            )
        return (
            f"{saved}{name} has access to several properties and an administrator needs to choose "
            "which one to report on. I’ll be ready to run this once they have.",
            "ADMIN_REQUIRED", data,
        )
    data.update(integration_id=a.integration_id, capabilities=a.missing_capabilities)
    if is_admin:
        return (
            f"{saved}{name} is connected, but this AI employee has not been given permission to use it. "
            "Approve read-only access for this role and I’ll run the request.",
            "GRANT_REQUIRED", data,
        )
    return (
        f"{saved}{name} is connected, but an administrator has not yet allowed this AI employee to "
        "use it. I’ll be ready to run this once they do.",
        "ADMIN_REQUIRED", data,
    )


async def save_pending(
    *, tenant_id: str, user_id: str, role_key: str, role_name: str,
    session_id: str | None, prompt: str, a: Assessment, db: AsyncSession,
) -> PendingTask:
    """One open task per (user, role, prompt): asking again refreshes it instead of piling up."""
    existing = (await db.execute(
        select(PendingTask).where(
            PendingTask.tenant_id == tenant_id,
            PendingTask.user_id == user_id,
            PendingTask.role_key == role_key,
            PendingTask.prompt == prompt[:4000],
            PendingTask.status == "waiting_setup",
        )
    )).scalar_one_or_none()
    payload = json.dumps({
        "provider_type": a.requirement.provider_type,
        "capabilities": list(a.requirement.capabilities),
        "purpose": a.requirement.purpose,
        "roles": list(a.requirement.roles),
        "needs_property": a.requirement.needs_property,
    })
    if existing:
        existing.blocking_state = a.state
        existing.requirement_json = payload
        await db.flush()
        await db.refresh(existing)
        return existing
    task = PendingTask(
        id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, role_key=role_key,
        role_name=role_name, session_id=session_id, prompt=prompt[:4000],
        status="waiting_setup", requirement_json=payload, blocking_state=a.state,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


def requirement_of(task: PendingTask) -> Requirement | None:
    try:
        d = json.loads(task.requirement_json or "{}")
        return Requirement(d["provider_type"], tuple(d["capabilities"]), d.get("purpose", ""),
                           tuple(d.get("roles", ())), bool(d.get("needs_property", False)))
    except (KeyError, ValueError, TypeError):
        return None


def grantable(req: Requirement) -> tuple[bool, str]:
    """
    An admin may approve a task's requirement in one click only if every
    capability is read-only and low risk - never a write or HIGH-risk action.
    """
    provider = integration_registry.get(req.provider_type)
    if provider is None:
        return False, "unknown provider"
    for key in req.capabilities:
        cap = provider.get_capability(key)
        if cap is None:
            return False, f"unknown capability {key}"
        if cap.category not in (CapabilityCategory.READ, CapabilityCategory.ANALYTICS):
            return False, f"{key} is not read-only"
        if cap.risk_level != RiskLevel.LOW:
            return False, f"{key} is not low risk"
    return True, ""
