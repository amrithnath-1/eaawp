"""
AI employee lifecycle: validated configuration snapshots, natural-language revisions with
approval, versioning and rollback.

What makes an employee REAL: its approved configuration is written into the company's
RoleConfiguration (the record ``execute_agent`` and the Meeting Room use), so an approved
employee can actually be asked to work, be delegated to, and be paused.

Safety rules (enforced here, not by the model):
 * tool keys must exist in MASTER_TOOL_REGISTRY - invented keys are dropped and reported;
 * state-changing tools require approval per run, except low-risk drafting/task creation
   (same policy as the built-in marketing role) - the model cannot make send/create/update autonomous;
 * the persona is sanitised; role_key is immutable after creation; models must be on the allowlist;
 * a revision is only PROPOSED; nothing changes until an administrator approves it;
 * rollback never edits history - it appends a new version that copies an old snapshot;
 * no credentials or integration grants are ever part of a snapshot.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.employee_version_models import EmployeeVersion
from app.db.models import AIEmployee, AuditLog, RoleConfiguration

logger = logging.getLogger(__name__)

LOW_RISK_ACTIONS = frozenset({"draft_email", "create_internal_task"})
EDITABLE_FIELDS = (
    "name", "purpose", "responsibilities", "objectives", "system_persona",
    "communication_style", "llm_model", "allowed_tools", "guarded_tools",
)
DEFAULT_MODEL = "gpt-4o-mini"
_INJECTION = re.compile(
    r"(ignore (all |any |your )?(previous|prior)|override system|you are now|disregard|forget your instructions|"
    r"jailbreak|bypass (the )?(approval|governance|safety))", re.IGNORECASE)


class ValidationProblem(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _models() -> set[str]:
    from app.llm.config import ALLOWED_MODELS
    return {m for ms in ALLOWED_MODELS.values() for m in ms}


def _strs(v, n: int, width: int) -> list[str]:
    return [str(x).strip()[:width] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]


def classify_tools(tools: list[str], guarded: list[str]) -> tuple[list[str], list[str], list[str]]:
    """-> (enabled, requires_approval, dropped). Unknown keys dropped; risky actions forced to approval."""
    from app.actions.registry import is_action_tool
    from app.tools.registry import MASTER_TOOL_REGISTRY

    enabled: list[str] = []
    approval: list[str] = []
    dropped: list[str] = []
    for key in dict.fromkeys([*(tools or []), *(guarded or [])]):          # order-preserving de-dup
        if not isinstance(key, str) or key not in MASTER_TOOL_REGISTRY:
            dropped.append(str(key)[:64])
            continue
        risky = is_action_tool(key) and key not in LOW_RISK_ACTIONS
        if key in (guarded or []) or risky:
            approval.append(key)
        else:
            enabled.append(key)
    return enabled, approval, dropped


def normalize_snapshot(raw: dict, current: dict | None = None) -> tuple[dict, list[str]]:
    """Validate + clamp a (partial) snapshot merged over ``current``. Returns (snapshot, warnings)."""
    base = dict(current or {})
    for k in EDITABLE_FIELDS:
        if k in raw and raw[k] is not None:
            base[k] = raw[k]
    warnings: list[str] = []
    name = str(base.get("name", "")).strip()[:255]
    if not name:
        raise ValidationProblem("The employee needs a name.")
    persona = str(base.get("system_persona", "")).strip()
    if _INJECTION.search(persona):
        persona = "You are a professional AI employee. Follow your configured responsibilities."
        warnings.append("The persona contained instruction-override wording and was replaced with a safe default.")
    model = str(base.get("llm_model") or DEFAULT_MODEL)
    if model not in _models():
        warnings.append(f"Model '{model[:40]}' is not allowed; using {DEFAULT_MODEL}.")
        model = DEFAULT_MODEL
    enabled, approval, dropped = classify_tools(
        [t for t in base.get("allowed_tools", []) if isinstance(t, str)],
        [t for t in base.get("guarded_tools", []) if isinstance(t, str)])
    if dropped:
        warnings.append("Unknown tools were removed: " + ", ".join(dropped[:8]))
    snap = {
        "name": name,
        "purpose": str(base.get("purpose", "")).strip()[:1000],
        "responsibilities": _strs(base.get("responsibilities"), 10, 200),
        "objectives": _strs(base.get("objectives"), 10, 200),
        "system_persona": persona[:2000],
        "communication_style": (str(base.get("communication_style") or "Concise").strip() or "Concise")[:32],
        "llm_model": model,
        "allowed_tools": enabled,
        "guarded_tools": approval,
    }
    return snap, warnings


def diff(before: dict, after: dict) -> list[dict]:
    return [{"field": k, "before": before.get(k), "after": after.get(k)}
            for k in EDITABLE_FIELDS if before.get(k) != after.get(k)]


def snapshot_of_role(row: RoleConfiguration, employee_name: str = "") -> dict:
    scopes = json.loads(row.tool_scopes_json or "[]")
    return {
        "name": employee_name or row.agent_name or row.role_name,
        "purpose": row.description or "",
        "responsibilities": json.loads(row.responsibilities_json or "[]"),
        "objectives": json.loads(row.objectives_json or "[]"),
        "system_persona": row.system_persona or "",
        "communication_style": row.communication_style or "Concise",
        "llm_model": row.llm_model or DEFAULT_MODEL,
        "allowed_tools": [t["tool_key"] for t in scopes if t.get("governance") == "enabled"],
        "guarded_tools": [t["tool_key"] for t in scopes if t.get("governance") == "requires_approval"],
    }


async def apply_snapshot(db: AsyncSession, tenant_id: str, role_key: str, snap: dict) -> RoleConfiguration:
    """Write the snapshot into the company's role configuration (what the agent runs with)."""
    row = (await db.execute(select(RoleConfiguration).where(
        RoleConfiguration.tenant_id == tenant_id, RoleConfiguration.role_key == role_key))).scalar_one_or_none()
    if row is None:
        row = RoleConfiguration(id=str(uuid.uuid4()), tenant_id=tenant_id, role_key=role_key)
        db.add(row)
    scopes = (
        [{"name": k, "tool_key": k, "governance": "enabled", "description": ""} for k in snap["allowed_tools"]]
        + [{"name": k, "tool_key": k, "governance": "requires_approval", "description": ""} for k in snap["guarded_tools"]]
    )
    row.role_name = snap["name"]
    row.agent_name = snap["name"]
    row.description = snap["purpose"]
    row.responsibilities_json = json.dumps(snap["responsibilities"])
    row.objectives_json = json.dumps(snap["objectives"])
    row.system_persona = snap["system_persona"]
    row.communication_style = snap["communication_style"]
    row.llm_model = snap["llm_model"]
    row.tool_scopes_json = json.dumps(scopes)
    await db.flush()
    return row


def audit(db: AsyncSession, tenant_id: str, actor: str, event: str, employee_id: str | None = None) -> None:
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=tenant_id, ai_employee_id=employee_id, actor=actor,
                    event=event[:500], department="admin", status="ok"))


async def role_key_taken(db: AsyncSession, tenant_id: str, role_key: str) -> bool:
    n = (await db.execute(select(func.count()).select_from(RoleConfiguration).where(
        RoleConfiguration.tenant_id == tenant_id, RoleConfiguration.role_key == role_key))).scalar_one()
    m = (await db.execute(select(func.count()).select_from(AIEmployee).where(
        AIEmployee.tenant_id == tenant_id, AIEmployee.role_key == role_key))).scalar_one()
    return bool(n or m)


async def create_first_version(db: AsyncSession, tenant_id: str, employee: AIEmployee, snap: dict, by: str,
                               instruction: str = "") -> EmployeeVersion:
    v = EmployeeVersion(id=str(uuid.uuid4()), tenant_id=tenant_id, ai_employee_id=employee.id, version=1,
                        status="current", snapshot_json=json.dumps(snap), change_summary="Created",
                        instruction=instruction[:2000], created_by=by, decided_by=by, decided_at=_now())
    db.add(v)
    await apply_snapshot(db, tenant_id, employee.role_key, snap)
    await db.flush()
    return v


async def versions_of(db: AsyncSession, tenant_id: str, employee_id: str) -> list[EmployeeVersion]:
    return list((await db.execute(select(EmployeeVersion).where(
        EmployeeVersion.tenant_id == tenant_id, EmployeeVersion.ai_employee_id == employee_id)
        .order_by(EmployeeVersion.version.desc()))).scalars().all())


def current_of(versions: list[EmployeeVersion]) -> EmployeeVersion | None:
    return next((v for v in versions if v.status == "current"), None)


async def _next_number(db: AsyncSession, tenant_id: str, employee_id: str) -> int:
    return (await db.execute(select(func.coalesce(func.max(EmployeeVersion.version), 0)).where(
        EmployeeVersion.tenant_id == tenant_id, EmployeeVersion.ai_employee_id == employee_id))).scalar_one() + 1


_REVISE_SYSTEM = (
    "You revise the configuration of an AI employee for a company. You receive the CURRENT configuration "
    "and a change request. Reply with JSON only, containing ONLY the fields that should change, chosen from: "
    "name, purpose, responsibilities, objectives, system_persona, communication_style, llm_model, "
    "allowed_tools, guarded_tools. Use only these tool keys: {tools}. Never include credentials. "
    "Keep system_persona professional and role-focused."
)


async def propose_revision(db: AsyncSession, tenant_id: str, employee: AIEmployee, instruction: str, by: str) -> tuple[EmployeeVersion, list[str]]:
    """LLM turns a plain-language request into a PROPOSED version (validated, nothing applied)."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.llm import get_llm_gateway
    from app.tools.registry import MASTER_TOOL_REGISTRY

    versions = await versions_of(db, tenant_id, employee.id)
    cur = current_of(versions)
    if cur is None:
        raise ValidationProblem("This employee has no active configuration to revise.")
    current = json.loads(cur.snapshot_json)
    gw = get_llm_gateway()
    if not gw.health().is_ready:
        raise RuntimeError("The language model is not available, so the change cannot be interpreted right now.")
    try:
        resp = await gw.get_chat_model(temperature=0).ainvoke([
            SystemMessage(content=_REVISE_SYSTEM.format(tools=", ".join(sorted(MASTER_TOOL_REGISTRY)))),
            HumanMessage(content=f"CURRENT:\n{json.dumps(current)}\n\nCHANGE REQUEST:\n{instruction}"),
        ])
        text = resp.content if isinstance(resp.content, str) else ""
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        changes = json.loads(text)
        if not isinstance(changes, dict):
            raise ValueError("not an object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Employee revision could not be interpreted: %s", type(exc).__name__)
        raise ValidationProblem("I could not turn that into a configuration change. Please rephrase it.") from exc
    changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}          # role_key etc. can never change
    proposed, warnings = normalize_snapshot(changes, current)
    changed = diff(current, proposed)
    if not changed:
        raise ValidationProblem("That request would not change anything about this employee.")
    for old in versions:                                                           # one open proposal at a time
        if old.status == "proposed":
            old.status, old.decided_by, old.decided_at = "rejected", "system", _now()
            old.change_summary = (old.change_summary + " (replaced by a newer proposal)")[:1000]
    v = EmployeeVersion(id=str(uuid.uuid4()), tenant_id=tenant_id, ai_employee_id=employee.id,
                        version=await _next_number(db, tenant_id, employee.id), status="proposed",
                        snapshot_json=json.dumps(proposed), instruction=instruction[:2000], created_by=by,
                        change_summary="Changes: " + ", ".join(c["field"] for c in changed))
    db.add(v)
    await db.flush()
    return v, warnings


async def approve_version(db: AsyncSession, tenant_id: str, employee: AIEmployee, v: EmployeeVersion, by: str) -> None:
    if v.status != "proposed":
        raise ValidationProblem(f"Version {v.version} is {v.status}, not a pending proposal.")
    await _make_current(db, tenant_id, employee, v, by)
    audit(db, tenant_id, by, f"approved configuration v{v.version} of '{employee.name}'", employee.id)


async def reject_version(db: AsyncSession, tenant_id: str, employee: AIEmployee, v: EmployeeVersion, by: str) -> None:
    if v.status != "proposed":
        raise ValidationProblem(f"Version {v.version} is {v.status}, not a pending proposal.")
    v.status, v.decided_by, v.decided_at = "rejected", by, _now()
    audit(db, tenant_id, by, f"rejected configuration v{v.version} of '{employee.name}'", employee.id)
    await db.flush()


async def rollback_to(db: AsyncSession, tenant_id: str, employee: AIEmployee, target: EmployeeVersion, by: str) -> EmployeeVersion:
    if target.status not in ("superseded", "current"):
        raise ValidationProblem("Only a configuration that was in use can be restored.")
    versions = await versions_of(db, tenant_id, employee.id)
    cur = current_of(versions)
    if cur is not None and cur.id == target.id:
        raise ValidationProblem("That version is already the current one.")
    snap, _ = normalize_snapshot(json.loads(target.snapshot_json))              # re-validated: today's rules apply
    new = EmployeeVersion(id=str(uuid.uuid4()), tenant_id=tenant_id, ai_employee_id=employee.id,
                          version=await _next_number(db, tenant_id, employee.id), status="proposed",
                          snapshot_json=json.dumps(snap), created_by=by,
                          change_summary=f"Rollback to version {target.version}")
    db.add(new)
    await db.flush()
    await _make_current(db, tenant_id, employee, new, by)
    audit(db, tenant_id, by, f"rolled '{employee.name}' back to v{target.version} (now v{new.version})", employee.id)
    return new


async def _make_current(db: AsyncSession, tenant_id: str, employee: AIEmployee, v: EmployeeVersion, by: str) -> None:
    for other in await versions_of(db, tenant_id, employee.id):
        if other.status == "current" and other.id != v.id:
            other.status = "superseded"
    v.status, v.decided_by, v.decided_at = "current", by, _now()
    snap = json.loads(v.snapshot_json)
    employee.name = snap["name"]
    await apply_snapshot(db, tenant_id, employee.role_key, snap)
    await db.flush()


BLOCKED_STATUSES = {"PAUSED", "DISABLED", "ARCHIVED"}


async def employee_is_blocked(db: AsyncSession, tenant_id: str, role_key: str) -> bool:
    """True when the company has employees for this role and none is active (paused/disabled/archived)."""
    rows = (await db.execute(select(AIEmployee).where(
        AIEmployee.tenant_id == tenant_id, AIEmployee.role_key == role_key))).scalars().all()
    if not rows:
        return False                                                           # built-in role without an employee record
    return not any(e.is_active and (e.status or "").upper() not in BLOCKED_STATUSES for e in rows)
