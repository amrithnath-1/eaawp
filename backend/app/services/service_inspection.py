"""
Answers about connected services that come from EAAWP's own records, not from the language model.

Each answer is built from evidence — the integration record, the tool registry (with real input schemas), the
capability grants, the recorded tool executions and, where asked for, a live check of the server — and says where
each fact came from. Nothing here returns credentials, server URLs or tokens.

  status(...)        connection state of the named service(s)
  discovery(...)     the tools a service provides, their inputs, and whether this AI employee may use each one
  diagnostics(...)   recent failures with their error class, what is needed, and a live check (administrators)
  permissions(...)   which AI employees may use which of a service's tools
  execution_check()  before a tool runs: connected? granted? — returns a refusal reason, or None to proceed
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.integration_models import CapabilityGrant, Integration
from app.db.toolhub_models import ToolExecution, ToolRecord
from app.services.request_routing import ServiceRef

MCP_TOOL_PREFIX = "mcp_tool:"


@dataclass
class Answer:
    message: str
    summary: str                 # one line for the plan ("[ROUTE] tool_discovery → 3 tools from registry")


def _when(dt: datetime | None) -> str:
    if not dt:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


async def _rows(db: AsyncSession, tenant_id: str, services: list[ServiceRef]) -> list[Integration]:
    ids = [s.id for s in services]
    if not ids:
        return []
    res = await db.execute(select(Integration).where(Integration.tenant_id == tenant_id, Integration.id.in_(ids)))
    by_id = {r.id: r for r in res.scalars()}
    return [by_id[i] for i in ids if i in by_id]


async def _grants(db: AsyncSession, tenant_id: str, integration_id: str) -> list[CapabilityGrant]:
    res = await db.execute(select(CapabilityGrant).where(
        CapabilityGrant.tenant_id == tenant_id, CapabilityGrant.integration_id == integration_id,
        CapabilityGrant.is_granted == True))  # noqa: E712
    return list(res.scalars())


def _role_grants(grants: list[CapabilityGrant], role_key: str) -> set[str]:
    return {g.capability_key for g in grants if g.role_key == role_key}


async def _tools(db: AsyncSession, tenant_id: str, row: Integration) -> tuple[list[dict], str]:
    """The service's tools with their input schemas: the registry first, the connection record as fallback."""
    if row.provider_type == "mcp":
        res = await db.execute(select(ToolRecord).where(
            ToolRecord.tenant_id == tenant_id, ToolRecord.integration_id == row.id, ToolRecord.source == "mcp",
            ToolRecord.status == "active").order_by(ToolRecord.key))
        recs = list(res.scalars())
        if recs:
            seen = max((r.last_seen_at or r.updated_at for r in recs), default=None)
            return ([{"name": r.key, "description": r.description, "schema": json.loads(r.input_schema_json or "{}"),
                      "risk": r.risk_class} for r in recs], f"tool registry, last discovered {_when(seen)}")
        try:
            info = json.loads(row.account_info_json or "{}")
        except ValueError:
            info = {}
        tools = [{"name": t.get("name"), "description": t.get("description", ""),
                  "schema": {"properties": {a: {} for a in (t.get("args") or [])}}, "risk": ""}
                 for t in info.get("mcp_tools") or [] if t.get("name")]
        return tools, f"connection record, last tested {_when(row.last_tested_at)}"
    from app.integrations.integration_registry import integration_registry
    provider = integration_registry.get(row.provider_type)
    caps = provider.get_capabilities() if provider else []
    return ([{"name": c.key, "description": c.description, "schema": {}, "risk": c.risk_level.value} for c in caps],
            "provider definition")


def _args_line(schema: dict) -> str:
    props = (schema or {}).get("properties") or {}
    req = set((schema or {}).get("required") or [])
    if not props:
        return "no inputs"
    parts = []
    for k, v in list(props.items())[:12]:
        typ = v.get("type", "") if isinstance(v, dict) else ""
        parts.append(f"{k}{' (required)' if k in req else ''}{': ' + typ if typ else ''}")
    return ", ".join(parts)


def _may_use(row: Integration, tool: str, mine: set[str]) -> bool:
    if row.provider_type == "mcp":
        return "call_tool" in mine and f"{MCP_TOOL_PREFIX}{tool}" in mine
    return tool in mine


def _no_service(kind: str) -> Answer:
    return Answer(f"I couldn't find a connected service matching that request. Connected services are listed in "
                  f"Integrations; name one of them and I'll check its {kind}.", "no matching integration")


# ── Status ────────────────────────────────────────────────────────────────────

async def status(db: AsyncSession, tenant_id: str, services: list[ServiceRef]) -> Answer:
    rows = await _rows(db, tenant_id, services)
    if not rows:
        return _no_service("connection")
    lines = []
    for r in rows:
        state = r.status.upper() + ("" if r.is_enabled or r.status != "connected" else " (switched off)")
        extra = ""
        if r.provider_type == "mcp":
            tools, src = await _tools(db, tenant_id, r)
            extra = f"; {len(tools)} tool(s) known ({src})"
        err = f"; last error: {r.error_message[:200]}" if r.status == "failed" and r.error_message else ""
        lines.append(f"- **{r.display_name}** ({r.provider_type}): {state}; last tested {_when(r.last_tested_at)}"
                     f"{extra}{err}")
    return Answer("Connection status (from the saved connection records):\n" + "\n".join(lines),
                  ", ".join(f"{r.display_name}={r.status}" for r in rows))


# ── Discovery ─────────────────────────────────────────────────────────────────

async def discovery(db: AsyncSession, tenant_id: str, role_key: str, services: list[ServiceRef],
                    refresh: bool) -> Answer:
    rows = await _rows(db, tenant_id, services)
    if not rows:
        return _no_service("tools")
    parts, total = [], 0
    for r in rows:
        note = ""
        if refresh and r.provider_type == "mcp" and r.status == "connected":
            # A live tools/list from the server (read-only); it also updates the registry (added/changed/removed).
            from app.integrations import manager
            try:
                await manager.discover_integration_entities(r.id, tenant_id, db)
                note = " Tool list refreshed from the server just now."
            except Exception as exc:  # noqa: BLE001
                note = f" Live refresh failed ({str(exc)[:200]}); showing the last known list."
        tools, src = await _tools(db, tenant_id, r)
        total += len(tools)
        mine = _role_grants(await _grants(db, tenant_id, r.id), role_key)
        lines = [f"- `{t['name']}` — {(t['description'] or '').strip()[:160] or 'no description'}  \n"
                 f"  Inputs: {_args_line(t['schema'])}. "
                 f"{'This AI employee may use it.' if _may_use(r, t['name'], mine) else 'Not granted to this AI employee.'}"
                 for t in tools[:40]]
        more = f"\n- …and {len(tools) - 40} more" if len(tools) > 40 else ""
        parts.append(f"**{r.display_name}** ({r.provider_type}, {r.status}) — {len(tools)} tool(s), from the {src}."
                     f"{note}\n" + ("\n".join(lines) + more if lines else "- No tools discovered yet."))
    tail = ("\n\nDiscovering a tool grants nothing: an administrator grants each tool to an AI employee before it can"
            " run.")
    return Answer("\n\n".join(parts) + tail, f"{total} tool(s) listed" + (" (live refresh)" if refresh else ""))


# ── Permissions ───────────────────────────────────────────────────────────────

async def permissions(db: AsyncSession, tenant_id: str, role_key: str, services: list[ServiceRef],
                      is_admin: bool) -> Answer:
    rows = await _rows(db, tenant_id, services)
    if not rows:
        return _no_service("access")
    from app.services.role_charter import ROLE_SCOPES
    names = {k: v[0] for k, v in ROLE_SCOPES.items()}
    parts = []
    for r in rows:
        grants = await _grants(db, tenant_id, r.id)
        by_role: dict[str, set[str]] = {}
        for g in grants:
            if is_admin or g.role_key == role_key:
                by_role.setdefault(g.role_key, set()).add(g.capability_key)
        if not by_role:
            who = "No AI employee has" if is_admin else "This AI employee has not been"
            parts.append(f"**{r.display_name}**: {who} granted any of its tools.")
            continue
        lines = []
        for rk, caps in sorted(by_role.items()):
            if r.provider_type == "mcp":
                tools = sorted(c[len(MCP_TOOL_PREFIX):] for c in caps if c.startswith(MCP_TOOL_PREFIX))
                usable = "call_tool" in caps
                desc = (", ".join(f"`{t}`" for t in tools) if tools else "no individual tools")
                desc += "" if usable else " (missing the base `call_tool` grant, so none can run yet)"
            else:
                desc = ", ".join(f"`{c}`" for c in sorted(caps))
            lines.append(f"- {names.get(rk, rk)}: {desc}")
        parts.append(f"**{r.display_name}** ({r.provider_type}) — grants recorded in EAAWP:\n" + "\n".join(lines))
    scope = "" if is_admin else "\n\n(Only this AI employee's own access is shown; an administrator can see all.)"
    return Answer("\n\n".join(parts) + scope, f"grants of {len(rows)} service(s)")


# ── Diagnostics ───────────────────────────────────────────────────────────────

async def diagnostics(db: AsyncSession, tenant_id: str, role_key: str, services: list[ServiceRef],
                      is_admin: bool) -> Answer:
    from app.toolhub import diagnostics as diag
    rows = await _rows(db, tenant_id, services)
    if not rows:
        return _no_service("recent failures")
    parts = []
    for r in rows:
        lines = [f"- Connection record: {r.status.upper()}, last tested {_when(r.last_tested_at)}"
                 + (f", last error: {r.error_message[:200]}" if r.error_message else "")]
        prefix = f"integration_{r.id.replace('-', '')[:8]}_"
        res = await db.execute(select(ToolExecution).where(
            ToolExecution.tenant_id == tenant_id, ToolExecution.tool_key.like(f"{prefix}%"))
            .order_by(ToolExecution.started_at.desc()).limit(20))
        runs = list(res.scalars())
        failed = [x for x in runs if x.status != "success"]
        if runs:
            lines.append(f"- Recorded runs of its tools: {len(runs)} recent, {len(failed)} failed or blocked.")
        else:
            lines.append("- No recorded runs of its tools yet.")
        for x in failed[:5]:
            cat = x.error_category or diag.classify_error(x.error_message or "") or "execution_error"
            need = diag.advice(cat)
            lines.append(f"  - {_when(x.started_at)} · {x.tool_label or x.tool_key} · **{cat}**"
                         f"{' after ' + str(x.retries) + ' retr' + ('y' if x.retries == 1 else 'ies') if x.retries else ''}"
                         f": {(x.error_message or '')[:200]}" + (f" — {need}" if need else "")
                         + (f" (recovery: {x.recovery[:120]})" if x.recovery else ""))
        if is_admin and r.encrypted_credentials:
            from app.integrations import manager
            try:
                live = await manager.test_integration(r.id, tenant_id, db)
                lines.append(f"- Live check just now: {'reachable' if live.success else 'FAILED'}"
                             + (f" — {live.error_message[:200]} (class: {diag.classify_error(live.error_message)})"
                                if not live.success and live.error_message else "")
                             + (f"; {len(live.account_info.get('mcp_tools') or [])} tool(s) offered"
                                if live.success and r.provider_type == "mcp" else ""))
            except Exception as exc:  # noqa: BLE001
                lines.append(f"- Live check could not run: {str(exc)[:200]}")
        elif not is_admin:
            lines.append("- A live connection check needs an administrator (Integrations → TEST NOW).")
        mine = _role_grants(await _grants(db, tenant_id, r.id), role_key)
        if r.provider_type == "mcp" and "call_tool" not in mine:
            lines.append("- This AI employee has no `call_tool` grant for it, so its tools cannot run from this chat.")
        parts.append(f"**{r.display_name}** ({r.provider_type}):\n" + "\n".join(lines))
    return Answer("Diagnosis from EAAWP's records:\n\n" + "\n\n".join(parts),
                  f"{len(rows)} service(s) diagnosed")


# ── Before execution ──────────────────────────────────────────────────────────

async def execution_check(db: AsyncSession, tenant_id: str, role_key: str,
                          services: list[ServiceRef]) -> tuple[Answer | None, list[Integration]]:
    """None when the named service(s) can run for this AI employee; otherwise the reason (nothing is executed)."""
    rows = await _rows(db, tenant_id, services)
    if not rows:
        return None, []
    usable, problems = [], []
    for r in rows:
        if r.status != "connected" or not r.is_enabled:
            problems.append(f"**{r.display_name}** is not connected (status: {r.status}"
                            f"{', switched off' if r.status == 'connected' and not r.is_enabled else ''}). "
                            "An administrator can reconnect it in Integrations (TEST NOW).")
            continue
        mine = _role_grants(await _grants(db, tenant_id, r.id), role_key)
        if r.provider_type == "mcp":
            tools = sorted(c[len(MCP_TOOL_PREFIX):] for c in mine if c.startswith(MCP_TOOL_PREFIX))
            if "call_tool" not in mine or not tools:
                problems.append(f"**{r.display_name}** is connected, but this AI employee has not been granted any of "
                                "its tools, so nothing was run. An administrator can grant the tools it needs "
                                "(Integrations → the server → grants, or by asking me in chat).")
                continue
        else:
            # Other providers: the readiness gate after this check saves the request as a pending task and shows the
            # setup card for a missing grant, so the request is resumable once access is granted.
            continue
        usable.append(r)
    if usable:
        return None, usable
    return Answer("\n\n".join(problems), "blocked before execution: " + "; ".join(
        "not connected" if "not connected" in p else "not granted" for p in problems)), []
