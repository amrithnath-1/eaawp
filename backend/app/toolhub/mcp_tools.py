"""
Granted MCP tools as native functions for the model — one function per tool, with that tool's real input schema.

The model then calls `mcp_<server>_<tool>(url=…, objective=…)` with typed fields, instead of writing a JSON string
holding a tool name and an arguments object. The tool name is fixed in code (it can never be null or invented), the
required fields are declared as required, and every call still goes through mcp_engine (grants, risk, server-side
validation against the full schema, audit, job following).

Also: check_task — the state / result of a long-running job (see mcp_tasks), for "is it done yet?".
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.toolhub import mcp_engine, mcp_schema, mcp_tasks

CHECK_TASK = "check_task"
MAX_NATIVE_TOOLS = 40


class _TaskArgs(BaseModel):
    task_id: str = Field(..., description="The EAAWP task id (or the server's job id) of a long-running job.")


async def native_tools(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str) -> dict[str, StructuredTool]:
    """{function name: tool} for every MCP tool granted to this role on a connected, enabled server."""
    from app.db.integration_models import CapabilityGrant, Integration
    from app.db.toolhub_models import ToolRecord
    grants = (await db.execute(select(CapabilityGrant).where(
        CapabilityGrant.tenant_id == tenant_id, CapabilityGrant.role_key == role_key,
        CapabilityGrant.is_granted == True))).scalars().all()  # noqa: E712
    by_server: dict[str, set[str]] = {}
    base: set[str] = set()
    for g in grants:
        if g.capability_key == "call_tool":
            base.add(g.integration_id)
        elif g.capability_key.startswith("mcp_tool:"):
            by_server.setdefault(g.integration_id, set()).add(g.capability_key.split(":", 1)[1])
    out: dict[str, StructuredTool] = {}
    for iid in sorted(base & set(by_server)):
        row = (await db.execute(select(Integration).where(Integration.id == iid, Integration.tenant_id == tenant_id))
               ).scalar_one_or_none()
        if row is None or row.provider_type != "mcp" or row.status != "connected" or not row.is_enabled:
            continue
        recs = (await db.execute(select(ToolRecord).where(
            ToolRecord.tenant_id == tenant_id, ToolRecord.integration_id == iid, ToolRecord.source == "mcp",
            ToolRecord.status == "active", ToolRecord.key.in_(sorted(by_server[iid]))))).scalars().all()
        all_names = {k: {"schema": {}, "description": ""} for k in (await db.execute(select(ToolRecord.key).where(
            ToolRecord.tenant_id == tenant_id, ToolRecord.integration_id == iid, ToolRecord.source == "mcp",
            ToolRecord.status == "active"))).scalars()}
        for rec in recs[:MAX_NATIVE_TOOLS]:
            starts_jobs = mcp_tasks._sibling(rec.key, all_names, "status") is not None
            out[mcp_schema.function_name(iid, rec.key)] = _tool(db, tenant_id, role_key, plan_id, row, rec,
                                                                starts_jobs)
    if out:
        out[CHECK_TASK] = _check_task_tool(db, tenant_id)
    return out


def _tool(db, tenant_id, role_key, plan_id, row, rec, starts_jobs: bool = False) -> StructuredTool:
    schema = json.loads(rec.input_schema_json or "{}")
    iid, tool_name, server = row.id, rec.key, row.display_name

    async def _run(**kwargs: Any) -> str:
        return await mcp_engine.run(db, tenant_id, role_key, plan_id, iid, tool_name, kwargs)

    desc = (f"[{server} · MCP tool {tool_name}] {(rec.description or '').strip()[:700]} "
            f"Inputs: {mcp_schema.describe(schema)}.")
    return StructuredTool.from_function(
        coroutine=_run, name=mcp_schema.function_name(iid, tool_name), description=desc[:1024],
        args_schema=mcp_schema.function_schema(schema),
        metadata={"integration_id": iid, "provider_type": "mcp", "capability_key": "call_tool",
                  "mcp_tool": tool_name, "server": server, "risk_class": rec.risk_class,
                  # A tool that starts jobs is never retried automatically: a retry would start the job again.
                  "idempotent": rec.risk_class == "read_only" and not starts_jobs})


def _check_task_tool(db: AsyncSession, tenant_id: str) -> StructuredTool:
    async def check_task(task_id: str) -> str:
        from app.db.toolhub_models import McpTask
        t = (await db.execute(select(McpTask).where(McpTask.tenant_id == tenant_id, McpTask.id == task_id))
             ).scalar_one_or_none()
        if t is None:
            t = (await db.execute(select(McpTask).where(McpTask.tenant_id == tenant_id, McpTask.remote_id == task_id)
                                  .order_by(McpTask.created_at.desc()).limit(1))).scalar_one_or_none()
        if t is None:
            return "[TOOL ERROR] check_task: no such job for this company (not found)."
        if t.state in mcp_tasks.ACTIVE:
            await mcp_tasks.poll_once(db, t)
        return mcp_tasks.describe(t)

    return StructuredTool.from_function(
        coroutine=check_task, name=CHECK_TASK, args_schema=_TaskArgs,
        description="The current state and, when finished, the result of a long-running MCP job started earlier "
                    "(by its EAAWP task id). Never starts anything.")
