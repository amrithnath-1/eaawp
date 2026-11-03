"""
MCP discovery → tool registry.

Every discovery of an MCP server (TEST NOW, Review tools, or a recovery refresh) is compared with the registry:
new tools are registered, changed descriptions/schemas are updated, tools the server no longer offers are marked
removed. Each run is kept as a snapshot (what changed, how long it took, or the error) for the health monitor, and
changes are written to the tool audit trail.

Discovering a tool never grants it: AI employees still need an explicit per-tool grant (mcp_tool:<name>).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.toolhub_models import McpDiscoverySnapshot, ToolEvent, ToolRecord
from app.toolhub import risk

logger = logging.getLogger(__name__)


def _schema_from_args(args: list[dict]) -> dict:
    """The compact catalogue's argument list as a JSON schema (types, descriptions, required)."""
    props, required = {}, []
    for a in args or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        t = a.get("type") if a.get("type") in ("string", "number", "integer", "boolean", "array", "object") else None
        props[a["name"]] = {**({"type": t} if t else {}), "description": a.get("description", "")}
        if a.get("required"):
            required.append(a["name"])
    return {"type": "object", "properties": props, "required": required}


def normalise(tools: list[dict]) -> list[dict]:
    """Accept the compact catalogue (name/description/args/hash) or full discovery entities (input_schema)."""
    out = []
    for t in tools or []:
        name = str(t.get("name") or t.get("entity_name") or "")[:128]
        if not name:
            continue
        schema = t.get("input_schema") or t.get("inputSchema")
        if not isinstance(schema, dict):
            schema = _schema_from_args(t.get("args") or [])
        desc = str(t.get("description") or "")[:2000]
        digest = t.get("hash") or hashlib.sha256(
            json.dumps({"d": desc, "s": schema}, sort_keys=True, default=str).encode()).hexdigest()[:32]
        out.append({"name": name, "description": desc, "schema": schema, "hash": str(digest)[:64]})
    return out


async def sync(db: AsyncSession, tenant_id: str, integration_id: str, tools: list[dict] | None, *,
               duration_ms: int = 0, error: str | None = None, actor: str = "discovery") -> dict:
    """Bring the registry in line with one discovery. Returns {added, removed, changed, tool_count}."""
    if error is not None or tools is None:
        db.add(McpDiscoverySnapshot(tenant_id=tenant_id, integration_id=integration_id, duration_ms=duration_ms,
                                    error=(error or "discovery failed")[:500]))
        await db.flush()
        return {"added": [], "removed": [], "changed": [], "tool_count": 0, "error": error}

    found = {t["name"]: t for t in normalise(tools)}
    rows = (await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.source == "mcp",
        ToolRecord.integration_id == integration_id))).scalars().all()
    known = {r.key: r for r in rows}
    now = datetime.now(timezone.utc)
    added, removed, changed = [], [], []

    for name, t in found.items():
        r = known.get(name)
        if r is None:
            r = ToolRecord(tenant_id=tenant_id, source="mcp", integration_id=integration_id, key=name, name=name,
                           description=t["description"], input_schema_json=json.dumps(t["schema"]),
                           risk_class=risk.classify(name), status="active", schema_hash=t["hash"],
                           created_by=actor, last_seen_at=now)
            db.add(r)
            added.append(name)
            continue
        if r.status == "removed":
            r.status = "active"
            added.append(name)
        elif r.schema_hash != t["hash"]:
            changed.append(name)
            r.current_version += 1
        r.description, r.input_schema_json, r.schema_hash = t["description"], json.dumps(t["schema"]), t["hash"]
        r.risk_class, r.last_seen_at, r.updated_at = risk.classify(name), now, now

    for name, r in known.items():
        if name not in found and r.status != "removed":
            r.status, r.updated_at = "removed", now
            removed.append(name)

    await db.flush()
    ids = {r.key: r.id for r in (await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.source == "mcp",
        ToolRecord.integration_id == integration_id))).scalars().all()}
    for kind, names in (("discovered", added), ("schema_changed", changed), ("removed", removed)):
        for n in names[:200]:
            db.add(ToolEvent(tenant_id=tenant_id, tool_id=ids.get(n), kind=kind, actor=actor,
                             detail=f"MCP tool '{n}' {kind.replace('_', ' ')} (connection {integration_id[:8]})."))
    digest = hashlib.sha256("|".join(sorted(f"{k}:{v['hash']}" for k, v in found.items())).encode()).hexdigest()
    db.add(McpDiscoverySnapshot(tenant_id=tenant_id, integration_id=integration_id, tool_count=len(found),
                                schema_hash=digest, added_json=json.dumps(added), removed_json=json.dumps(removed),
                                changed_json=json.dumps(changed), duration_ms=duration_ms))
    await db.flush()
    if added or removed or changed:
        logger.info("MCP discovery %s: +%d -%d ~%d", integration_id[:8], len(added), len(removed), len(changed))
    return {"added": added, "removed": removed, "changed": changed, "tool_count": len(found)}


async def refresh(db: AsyncSession, tenant_id: str, integration_id: str, actor: str = "recovery") -> dict:
    """Discover the server's tools again now (used by recovery when a tool is missing or its schema changed)."""
    import time

    from app.integrations import manager
    t0 = time.monotonic()
    try:
        res = await manager.discover_integration_entities(integration_id, tenant_id, db)
    except Exception as exc:  # noqa: BLE001
        return await sync(db, tenant_id, integration_id, None, duration_ms=int((time.monotonic() - t0) * 1000),
                          error=str(exc)[:300], actor=actor)
    return {"tool_count": res.entity_count, "refreshed": True}


def input_schema_of(db_row: Any) -> dict:
    try:
        return json.loads(db_row.input_schema_json or "{}")
    except ValueError:
        return {}
