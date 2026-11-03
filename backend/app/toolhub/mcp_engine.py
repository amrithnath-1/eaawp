"""
The one execution path for MCP tools, for every AI employee and every server.

  prepare()   DB only — tenant ownership, connected + enabled, the role's grants (call_tool + the specific tool),
              the tool's current schema from the registry, risk policy, argument validation, credentials (in memory).
              Nothing is sent unless every check passes; an invalid / missing / unknown tool name never gets here.
  dispatch()  network only — the server is asked for its live schema, the arguments are validated again against it,
              then tools/call. Safe to run many at once (real parallel execution: no DB session is touched).
  finish()    DB only — audit record; long-running jobs are recognised and handed to mcp_tasks (which follows them).

run() = prepare → (duplicate-job check) → dispatch → finish, for a single call.
Results are text for the model; failures start with a bracketed tag ([VALIDATION ERROR], [PERMISSION DENIED],
[TOOL ERROR], [TIMEOUT], [GOVERNANCE REQUIRED], [TASK …]) so the model and diagnostics can tell them apart.
Credentials never leave this module: they are decrypted in prepare(), used in dispatch() and cleared after.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.toolhub import mcp_schema

logger = logging.getLogger(__name__)

MAX_CORRECTIONS = 2           # invalid-argument retries the model gets per tool and answer


@dataclass
class Prepared:
    ok: bool
    text: str = ""                       # the refusal when not ok
    integration_id: str = ""
    display_name: str = ""
    tool_name: str = ""
    args: dict = field(default_factory=dict)
    schema: dict = field(default_factory=dict)
    description: str = ""
    credentials: dict = field(default_factory=dict, repr=False)
    risk: str = "read_only"
    existing_task: Any = None            # a duplicate of an active / recent job: its record instead of a new start


@dataclass
class Dispatched:
    ok: bool
    text: str
    duration_ms: int = 0


def _refuse(text: str, **kw) -> Prepared:
    return Prepared(ok=False, text=text, **kw)


async def prepare(db: AsyncSession, tenant_id: str, role_key: str, integration_id: str, tool_name: Any,
                  args: Any) -> Prepared:
    from app.db.integration_models import Integration
    from app.db.toolhub_models import ToolRecord
    from app.integrations.manager import MCP_TOOL_PREFIX, _decrypt_credentials, has_capability_grant
    from app.toolhub import risk as risk_mod
    from app.tools.dynamic_tool import _FORBIDDEN_PARAM_FIELDS

    if not mcp_schema.valid_tool_name(tool_name):
        return _refuse(f"[VALIDATION ERROR] The tool name {str(tool_name)[:60]!r} is missing or invalid. Nothing was "
                       "sent. Use one of the MCP tools in your tool list.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return _refuse(f"[VALIDATION ERROR] Arguments for '{tool_name}' must be a JSON object. Nothing was sent.")
    row = (await db.execute(select(Integration).where(
        Integration.id == integration_id, Integration.tenant_id == tenant_id))).scalar_one_or_none()
    if row is None or row.provider_type != "mcp":
        return _refuse("[PERMISSION DENIED] That MCP server is not one of this company's connections.")
    base = dict(integration_id=row.id, display_name=row.display_name, tool_name=tool_name)
    if row.status != "connected":
        return _refuse(f"[INTEGRATION ERROR] '{row.display_name}' is not connected (status: {row.status}). An "
                       "administrator can reconnect it (Integrations → TEST NOW).", **base)
    if not row.is_enabled:
        return _refuse(f"[PERMISSION DENIED] '{row.display_name}' is switched off.", **base)
    for cap in ("call_tool", f"{MCP_TOOL_PREFIX}{tool_name}"):
        if not await has_capability_grant(integration_id=row.id, role_key=role_key, capability_key=cap,
                                          tenant_id=tenant_id, db=db):
            return _refuse(f"[PERMISSION DENIED] This AI employee has not been granted '{tool_name}' on "
                           f"'{row.display_name}'. An administrator must grant it first. Nothing was sent.", **base)
    rec = (await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.integration_id == row.id, ToolRecord.source == "mcp",
        ToolRecord.key == tool_name))).scalar_one_or_none()
    if rec is None or rec.status != "active":
        return _refuse(f"[TOOL ERROR] '{tool_name}' is not in the registry of '{row.display_name}' (not found on "
                       "MCP server at the last discovery). The tool list should be refreshed.", **base)
    schema = json.loads(rec.input_schema_json or "{}")
    rc = risk_mod.classify(tool_name)
    if not risk_mod.runs_automatically(rc) and rc != "internal_modify":
        return _refuse(f"[GOVERNANCE REQUIRED] '{tool_name}' is classified {rc.replace('_', ' ')} and cannot run "
                       "automatically. A person must do this, or an administrator must provide an approved "
                       "workflow for it.", **base)
    bad = [k for k in args if str(k).lower() in _FORBIDDEN_PARAM_FIELDS]
    if bad:
        return _refuse(f"[VALIDATION ERROR] '{bad[0]}' cannot be passed to an MCP tool: credentials are never sent "
                       "through tool arguments. Nothing was sent.", **base)
    problems = mcp_schema.validate(args, schema)
    if problems:
        return _refuse(
            f"[VALIDATION ERROR] arguments for '{tool_name}' do not match its input schema: "
            + "; ".join(problems[:6]) + f". Inputs: {mcp_schema.describe(schema)}. Nothing was sent to the server. "
            "Call it again with corrected arguments.", **base, schema=schema)
    from app.toolhub import mcp_tasks
    existing = await mcp_tasks.find_duplicate(db, tenant_id, row.id, tool_name, args)
    creds = _decrypt_credentials(row.encrypted_credentials) if existing is None else {}
    return Prepared(ok=True, args=args, schema=schema, description=rec.description or "", credentials=creds,
                    risk=rc, existing_task=existing, **base)


async def dispatch(p: Prepared) -> Dispatched:
    """Network only. Uses (and then clears) the prepared credentials."""
    from app.integrations.providers.mcp_provider import MCPIntegrationProvider
    from app.integrations.integration_registry import integration_registry
    t0 = time.monotonic()
    provider = integration_registry.get("mcp") or MCPIntegrationProvider()
    try:
        res = await provider.execute(capability_key="call_tool", credentials=p.credentials,
                                     parameters={"tool_name": p.tool_name, "arguments": p.args})
    finally:
        p.credentials.clear()
    ms = int((time.monotonic() - t0) * 1000)
    if res.error:
        err = str(res.error)
        tag = ("[VALIDATION ERROR]" if "VALIDATION ERROR" in err else "[TIMEOUT]" if "did not respond" in err
               else "[TOOL ERROR]")
        return Dispatched(False, f"{tag} {p.display_name} · {p.tool_name}: {err.replace('VALIDATION ERROR: ', '')}", ms)
    data = res.data if isinstance(res.data, str) else json.dumps(res.data, ensure_ascii=False, default=str)
    return Dispatched(True, data, ms)


async def finish(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str | None, p: Prepared,
                 d: Dispatched) -> str:
    """Audit the call; if it started a job, record it and follow it. Returns the text for the model."""
    from app.tools.dynamic_tool import _write_dynamic_tool_audit
    try:
        await _write_dynamic_tool_audit(p.integration_id, f"mcp_tool:{p.tool_name}", mcp_schema.function_name(
            p.integration_id, p.tool_name), role_key, tenant_id, d.ok, 1 if d.ok else 0,
            None if d.ok else d.text[:300], db)
    except Exception:  # noqa: BLE001 - an audit failure must not lose the result
        logger.warning("MCP audit write failed", exc_info=True)
    if not d.ok:
        return d.text
    from app.toolhub import mcp_tasks
    return await mcp_tasks.after_call(db, tenant_id, role_key, plan_id, p, d.text)


async def run(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str | None, integration_id: str,
              tool_name: Any, args: Any) -> str:
    p = await prepare(db, tenant_id, role_key, integration_id, tool_name, args)
    if not p.ok:
        return p.text
    if p.existing_task is not None:
        from app.toolhub import mcp_tasks
        return await mcp_tasks.report_existing(db, p.existing_task)
    d = await dispatch(p)
    return await finish(db, tenant_id, role_key, plan_id, p, d)


async def run_many(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str | None,
                   calls: list[tuple[str, Any, Any]]) -> list[str]:
    """Several independent calls: checks one by one (shared DB session), network all at once, records in order."""
    prepared = [await prepare(db, tenant_id, role_key, iid, name, args) for iid, name, args in calls]
    sendable = [i for i, p in enumerate(prepared) if p.ok and p.existing_task is None]
    sent = await asyncio.gather(*(dispatch(prepared[i]) for i in sendable))
    by_index = dict(zip(sendable, sent))
    from app.toolhub import mcp_tasks
    out: list[str] = []
    for i, p in enumerate(prepared):
        if not p.ok:
            out.append(p.text)
        elif p.existing_task is not None:
            out.append(await mcp_tasks.report_existing(db, p.existing_task))
        else:
            out.append(await finish(db, tenant_id, role_key, plan_id, p, by_index[i]))
    return out
