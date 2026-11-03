"""
Tool Center API (administrators): tool registry, execution monitor, Tool Builder monitor, health and tool audit.

Everything is scoped to the administrator's own company (tenant from the JWT). No credentials, tool code inputs of
other tenants or raw secrets are ever returned; execution summaries are already secret-scrubbed when stored.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.integration_models import CapabilityGrant, Integration
from app.db.models import User
from app.db.session import get_db
from app.db.toolhub_models import McpDiscoverySnapshot, ToolEvent, ToolExecution, ToolGrant, ToolRecord, ToolVersion
from app.services.role_charter import ROLE_SCOPES
from app.toolhub import builder, mcp_sync, metrics, risk

router = APIRouter(prefix="/api/v1/toolhub", tags=["tool-center"])

ROLES = {k: v[0] for k, v in ROLE_SCOPES.items()}


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@router.get("/registry")
async def registry(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Every discovered MCP tool and generated tool, with source, version, status, risk, roles and performance."""
    tid = admin.tenant_id
    rows = (await db.execute(select(ToolRecord).where(ToolRecord.tenant_id == tid)
                             .order_by(ToolRecord.source, ToolRecord.key))).scalars().all()
    servers = {i.id: i.display_name for i in (await db.execute(select(Integration).where(
        Integration.tenant_id == tid, Integration.provider_type == "mcp"))).scalars()}
    mcp_grants = (await db.execute(select(CapabilityGrant).where(
        CapabilityGrant.tenant_id == tid, CapabilityGrant.is_granted == True,  # noqa: E712
        CapabilityGrant.capability_key.like("mcp_tool:%")))).scalars().all()
    gen_grants = (await db.execute(select(ToolGrant).where(ToolGrant.tenant_id == tid))).scalars().all()
    versions = (await db.execute(select(ToolVersion).where(ToolVersion.tenant_id == tid))).scalars().all()
    perf = {s["tool_key"]: s for s in await metrics.stats(db, tid)}
    out = []
    for r in rows:
        if r.source == "mcp":
            roles = sorted({g.role_key for g in mcp_grants
                            if g.integration_id == r.integration_id and g.capability_key == f"mcp_tool:{r.key}"})
            validation = "discovered"
            perf_key = r.key
        else:
            roles = sorted({g.role_key for g in gen_grants if g.tool_id == r.id})
            cur = next((v for v in versions if v.tool_id == r.id and v.version == r.current_version), None)
            validation = cur.status if cur else ("rejected" if r.status == "rejected" else "none")
            perf_key = r.key
        p = perf.get(perf_key) or {}
        out.append({
            "id": r.id, "key": r.key, "name": r.name, "description": r.description[:600], "source": r.source,
            "server": servers.get(r.integration_id or "", None), "integration_id": r.integration_id,
            "version": r.current_version, "status": r.status, "risk_class": r.risk_class,
            "policy": risk.POLICY.get(r.risk_class, "governed"), "roles": roles,
            "role_names": [ROLES.get(x, x) for x in roles], "validation": validation,
            "updated_at": _iso(r.updated_at), "last_seen_at": _iso(r.last_seen_at),
            "metrics": {k: p.get(k) for k in ("total", "success_rate", "avg_ms", "degraded", "last_failure")},
        })
    return {"tools": out, "roles": ROLES}


@router.get("/executions")
async def executions(status: str | None = Query(None, pattern="^(success|failed|blocked)$"),
                     tool: str | None = Query(None, max_length=255), limit: int = Query(100, ge=1, le=500),
                     admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    stmt = select(ToolExecution).where(ToolExecution.tenant_id == admin.tenant_id)
    if status:
        stmt = stmt.where(ToolExecution.status == status)
    if tool:
        stmt = stmt.where(ToolExecution.tool_key == tool)
    rows = (await db.execute(stmt.order_by(ToolExecution.started_at.desc()).limit(limit))).scalars().all()
    return {"executions": [{
        "id": e.id, "tool_key": e.tool_key, "tool_label": e.tool_label, "source": e.tool_source,
        "role": ROLES.get(e.role_key, e.role_key), "plan_id": e.plan_id, "status": e.status,
        "error_category": e.error_category, "error": e.error_message, "duration_ms": e.duration_ms,
        "retries": e.retries, "recovery": e.recovery, "input": e.input_summary, "output": e.output_summary,
        "started_at": _iso(e.started_at)} for e in rows]}


@router.get("/builder")
async def builder_monitor(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Missing-capability requests, generated tools with every version and its validation report."""
    tid = admin.tenant_id
    reqs = (await db.execute(select(ToolEvent).where(ToolEvent.tenant_id == tid, ToolEvent.kind == "capability_request")
                             .order_by(ToolEvent.created_at.desc()).limit(100))).scalars().all()
    tools = (await db.execute(select(ToolRecord).where(ToolRecord.tenant_id == tid, ToolRecord.source == "generated")
                              .order_by(ToolRecord.updated_at.desc()))).scalars().all()
    versions = (await db.execute(select(ToolVersion).where(ToolVersion.tenant_id == tid)
                                 .order_by(ToolVersion.version))).scalars().all()

    def parsed(text: str, default):
        try:
            return json.loads(text)
        except ValueError:
            return default
    return {
        "requests": [{"at": _iso(e.created_at), "actor": e.actor, **parsed(e.detail, {"need": e.detail})} for e in reqs],
        "tools": [{
            "id": t.id, "key": t.key, "name": t.name, "description": t.description, "status": t.status,
            "current_version": t.current_version, "created_by": t.created_by, "created_at": _iso(t.created_at),
            "versions": [{"version": v.version, "status": v.status, "purpose": v.purpose, "created_at": _iso(v.created_at),
                          "created_by": v.created_by, "code": v.code, "input_schema": parsed(v.input_schema_json, {}),
                          "output_schema": parsed(v.output_schema_json, {}),
                          "dependencies": parsed(v.dependencies_json, []),
                          "attempts": parsed(v.validation_json, [])}
                         for v in versions if v.tool_id == t.id]} for t in tools],
    }


@router.get("/health")
async def health(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """MCP server status (latest discovery), degraded/slow tools, 14-day failure trend, recovery attempts."""
    tid = admin.tenant_id
    servers = (await db.execute(select(Integration).where(
        Integration.tenant_id == tid, Integration.provider_type == "mcp"))).scalars().all()
    snaps = (await db.execute(select(McpDiscoverySnapshot).where(McpDiscoverySnapshot.tenant_id == tid)
                              .order_by(McpDiscoverySnapshot.created_at.desc()).limit(500))).scalars().all()
    out_servers = []
    for s in servers:
        mine = [x for x in snaps if x.integration_id == s.id]
        last = mine[0] if mine else None
        out_servers.append({
            "integration_id": s.id, "name": s.display_name, "status": s.status, "enabled": s.is_enabled,
            "last_checked": _iso(s.last_tested_at), "error": s.error_message,
            "last_discovery": None if last is None else {
                "at": _iso(last.created_at), "tool_count": last.tool_count, "error": last.error,
                "duration_ms": last.duration_ms, "added": json.loads(last.added_json),
                "removed": json.loads(last.removed_json), "changed": json.loads(last.changed_json)},
            "discoveries": len(mine), "failed_discoveries": sum(1 for x in mine if x.error)})
    since = datetime.now(timezone.utc) - timedelta(days=14)
    rows = (await db.execute(select(ToolExecution).where(ToolExecution.tenant_id == tid,
                                                         ToolExecution.started_at >= since))).scalars().all()
    trend: dict[str, dict] = {}
    for e in rows:
        day = (e.started_at if e.started_at.tzinfo else e.started_at.replace(tzinfo=timezone.utc)).date().isoformat()
        d = trend.setdefault(day, {"day": day, "success": 0, "failed": 0, "avg_ms": 0, "_n": 0})
        d["success" if e.status == "success" else "failed"] += 1
        d["_n"] += 1
        d["avg_ms"] += (e.duration_ms - d["avg_ms"]) / d["_n"]
    for d in trend.values():
        d.pop("_n"); d["avg_ms"] = round(d["avg_ms"])
    perf = await metrics.stats(db, tid)
    return {
        "servers": out_servers,
        "tools": [p for p in perf if p["degraded"] or (p["success_rate"] is not None and p["success_rate"] < 0.8)
                  or p["avg_ms"] > 10000],
        "trend": sorted(trend.values(), key=lambda d: d["day"]),
        "recoveries": [{"tool_key": e.tool_key, "at": _iso(e.started_at), "status": e.status, "retries": e.retries,
                        "recovery": e.recovery, "error_category": e.error_category}
                       for e in sorted(rows, key=lambda e: e.started_at, reverse=True) if e.recovery][:100],
    }


@router.get("/audit")
async def audit(limit: int = Query(200, ge=1, le=1000), admin: User = Depends(require_admin),
                db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(ToolEvent).where(ToolEvent.tenant_id == admin.tenant_id)
                             .order_by(ToolEvent.created_at.desc()).limit(limit))).scalars().all()
    return {"events": [{"id": e.id, "at": _iso(e.created_at), "kind": e.kind, "actor": e.actor, "tool_id": e.tool_id,
                        "detail": e.detail[:2000]} for e in rows]}


class RoleBody(BaseModel):
    role_key: str = Field(..., max_length=128)


class VersionBody(BaseModel):
    version: int = Field(..., ge=1)


async def _generated(db: AsyncSession, tenant_id: str, tool_id: str) -> ToolRecord:
    r = (await db.execute(select(ToolRecord).where(ToolRecord.tenant_id == tenant_id, ToolRecord.id == tool_id,
                                                   ToolRecord.source == "generated"))).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "Generated tool not found.")
    return r


@router.post("/tools/{tool_id}/grant")
async def grant_tool(tool_id: str, body: RoleBody, admin: User = Depends(require_admin),
                     db: AsyncSession = Depends(get_db)) -> dict:
    if body.role_key not in ROLES:
        raise HTTPException(422, "Unknown AI employee role.")
    r = await _generated(db, admin.tenant_id, tool_id)
    if r.status != "active":
        raise HTTPException(409, "Only an active, validated tool can be granted.")
    await builder.grant(db, admin.tenant_id, r.id, body.role_key, admin.email or admin.id)
    return {"ok": True}


@router.post("/tools/{tool_id}/revoke")
async def revoke_tool(tool_id: str, body: RoleBody, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)) -> dict:
    r = await _generated(db, admin.tenant_id, tool_id)
    return {"ok": await builder.revoke(db, admin.tenant_id, r.id, body.role_key, admin.email or admin.id)}


@router.post("/tools/{tool_id}/deactivate")
async def deactivate_tool(tool_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    r = await _generated(db, admin.tenant_id, tool_id)
    if await builder.set_active(db, admin.tenant_id, r.id, False, admin.email or admin.id) is None:
        raise HTTPException(409, "This tool cannot be deactivated.")
    return {"ok": True}


@router.post("/tools/{tool_id}/activate")
async def activate_tool(tool_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    r = await _generated(db, admin.tenant_id, tool_id)
    if await builder.set_active(db, admin.tenant_id, r.id, True, admin.email or admin.id) is None:
        raise HTTPException(409, "This tool has no validated version to activate.")
    return {"ok": True}


@router.post("/tools/{tool_id}/rollback")
async def rollback_tool(tool_id: str, body: VersionBody, admin: User = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)) -> dict:
    r = await _generated(db, admin.tenant_id, tool_id)
    if await builder.rollback(db, admin.tenant_id, r.id, body.version, admin.email or admin.id) is None:
        raise HTTPException(409, "That version cannot be restored.")
    return {"ok": True}


@router.post("/mcp/{integration_id}/refresh")
async def refresh_mcp(integration_id: str, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)) -> dict:
    """Discover an MCP server's tools again now (registry update + snapshot)."""
    i = (await db.execute(select(Integration).where(Integration.tenant_id == admin.tenant_id,
                                                    Integration.id == integration_id,
                                                    Integration.provider_type == "mcp"))).scalar_one_or_none()
    if i is None:
        raise HTTPException(404, "MCP connection not found.")
    if i.status != "connected":
        raise HTTPException(409, "Test the connection first (TEST NOW).")
    return await mcp_sync.refresh(db, admin.tenant_id, integration_id, actor=admin.email or admin.id)
