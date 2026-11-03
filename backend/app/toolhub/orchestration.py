"""
Orchestration support for the chat agent (one engine for every AI employee; nothing here is role-specific).

- meta tools every AI employee gets:
    find_tools  – search all tools the company has (granted or not) for a capability; never runs anything
    build_tool  – Tool Builder (reuse check first; generation + sandbox validation; least-privilege grant)
    make_chart  – a chart from numbers the tools of this answer returned (verified server-side)
- generated_tools() – the role's granted, active generated tools as real callable tools (JSON-schema inputs)
- execute()  – runs one read/compute tool call with diagnosis, bounded retry of transient failures, an MCP tool-list
               refresh when a tool is missing or its schema changed, and an execution record (metrics)
- PARALLEL_SAFE – tools that touch no database session and may run concurrently within one round
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.toolhub import builder, charts, diagnostics, metrics

logger = logging.getLogger(__name__)

FIND_TOOLS, BUILD_TOOL, MAKE_CHART = "find_tools", "build_tool", "make_chart"
META_TOOLS = (FIND_TOOLS, BUILD_TOOL, MAKE_CHART)
NO_BUILD_ROLES = frozenset({"MEDICAL_ASSISTANT"})      # only approved healthcare workflows: no self-made tools


@dataclass
class TurnState:
    """What one chat turn accumulates across rounds."""
    evidence: list[str] = field(default_factory=list)       # successful tool outputs (for chart verification)
    charts: list[dict] = field(default_factory=list)
    new_tools: dict[str, Any] = field(default_factory=dict)  # tools built during this turn, to bind next round


class _FindArgs(BaseModel):
    need: str = Field(..., description="The capability you need, in plain words (e.g. 'crawl a whole website').")


class _BuildArgs(BaseModel):
    capability: str = Field(..., description="Exactly what the new tool must compute, in one sentence.")
    details: str = Field("", description="Inputs it receives, outputs it must return, rules, edge cases.")
    example_input_json: str = Field("", description="Optional JSON example of the input object.")


class _SeriesArg(BaseModel):
    name: str = Field(..., description="Series name shown in the legend, e.g. 'Clicks'.")
    values: list[Optional[float]] = Field(..., description="One number per label, in label order (null if missing).")


class _KpiArg(BaseModel):
    label: str
    value: float
    unit: str = ""


class _ChartArgs(BaseModel):
    title: str = Field("", description="Chart title.")
    type: str = Field("", description="bar | hbar (horizontal bars, for rankings or long labels) | line | area | pie | "
                                      "donut | scatter | histogram | kpi | table. Leave empty to choose from the data.")
    description: str = Field("", description="One sentence on what the chart shows.")
    labels: list[str] = Field(default_factory=list, description="Categories or dates on the x axis.")
    series: list[_SeriesArg] = Field(default_factory=list, description="One or more series (several = grouped / "
                                     "comparison chart). Scatter: series[0] = x values, series[1] = y values.")
    stacked: bool = Field(False, description="Stack the series (bar, hbar, area).")
    values: list[float] = Field(default_factory=list, description="Histogram only: the raw values to bin.")
    bins: int = Field(0, description="Histogram only: number of bins (0 = automatic).")
    kpis: list[_KpiArg] = Field(default_factory=list, description="KPI cards: label, value, unit.")
    unit: str = Field("", description="Unit of the values, e.g. '%', 'clicks', 'INR'.")
    x_label: str = ""
    y_label: str = ""
    source: str = Field("", description="Where the numbers came from (tool / service).")
    chart_json: str = Field("", description="(Older form) the whole chart as a JSON string. Prefer the fields.")


def meta_tools(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str, state: TurnState,
               actor: str) -> dict[str, StructuredTool]:
    async def find_tools(need: str) -> str:
        found = await builder.assess(db, tenant_id, role_key, need, limit=8)
        if not found["candidates"]:
            return "No existing tool matches. If the capability is a calculation or transformation over data you " \
                   "have, build_tool can create it."
        lines = []
        for c in found["candidates"]:
            access = {True: "you can use it", False: "exists but is NOT granted to you (an administrator can grant "
                      "it)", None: "usable if it is in your tool list"}[c["granted"]]
            lines.append(f"- {c['key']} [{c['source']}] score {c['score']}: {c['description'][:160]} — {access}")
        return "Existing tools for this need (best first):\n" + "\n".join(lines)

    async def build_tool(capability: str, details: str = "", example_input_json: str = "") -> str:
        try:
            example = json.loads(example_input_json) if example_input_json.strip() else None
        except ValueError:
            example = example_input_json[:1000]
        res = await builder.build(db, tenant_id, role_key, capability, details, example, actor=actor)
        if res.status == "registered" and res.tool_key:
            for t in await builder.usable(db, tenant_id, role_key):
                if t.key == res.tool_key:
                    state.new_tools[t.key] = _generated_tool(db, tenant_id, role_key, plan_id, t)
            return f"{res.message} It is now in your tool list as {res.tool_key}: call it with the inputs it describes."
        if res.status == "reused":
            return res.message
        return f"[TOOL ERROR] build_tool: {res.message}"

    async def make_chart(**fields: Any) -> str:
        legacy = fields.pop("chart_json", "") or ""
        if legacy.strip():
            try:
                raw = json.loads(legacy)
            except ValueError:
                return "[VALIDATION ERROR] make_chart: chart_json must be valid JSON (or use the chart fields)."
        else:
            raw = {k: (v.model_dump() if hasattr(v, "model_dump") else
                       [x.model_dump() if hasattr(x, "model_dump") else x for x in v] if isinstance(v, list) else v)
                   for k, v in fields.items() if v not in ("", None, [], 0) or k == "stacked"}
        spec, why = charts.build(raw, "\n".join(state.evidence))
        if spec is None:
            return f"[VALIDATION ERROR] make_chart: {why}"
        if len(state.charts) >= 6:
            return "[VALIDATION ERROR] make_chart: at most 6 charts per answer."
        state.charts.append(spec)
        return f"Chart '{spec['title']}' ({spec['type']}) added below the answer. Refer to it in your answer."

    tools = {
        FIND_TOOLS: StructuredTool.from_function(
            coroutine=find_tools, name=FIND_TOOLS, args_schema=_FindArgs,
            description="Search every tool this company has (built-in, integrations, MCP servers, generated tools) "
                        "for a capability, including tools not granted to you. Read-only; runs nothing."),
        MAKE_CHART: StructuredTool.from_function(
            coroutine=make_chart, name=MAKE_CHART, args_schema=_ChartArgs,
            description="Show a chart under your answer (bar, horizontal bar, grouped/stacked bars, line, area, "
                        "pie/donut, scatter, histogram, KPI cards or table), from numbers your tools returned in this "
                        "answer. Use it for comparisons, trends, shares, distributions and KPIs. Never write chart "
                        "JSON in your answer text — call this instead. Invented or unverified values are refused."),
    }
    if role_key not in NO_BUILD_ROLES:
        tools[BUILD_TOOL] = StructuredTool.from_function(
            coroutine=build_tool, name=BUILD_TOOL, args_schema=_BuildArgs,
            description="Create a new reusable internal tool for a CALCULATION or DATA TRANSFORMATION that no existing "
                        "tool or combination of tools can do (e.g. a business-specific score over rows you already "
                        "have). It first checks for an existing equivalent, then writes, tests and validates the tool "
                        "in a sandbox (no network, files or secrets). Use find_tools first. Not for fetching data.")
    return tools


def _generated_tool(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str, rec: Any) -> StructuredTool:
    try:
        schema = json.loads(rec.input_schema_json or "{}")
    except ValueError:
        schema = {}
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {}}

    async def run(**inputs: Any) -> str:
        return await builder.run(db, tenant_id, role_key, rec.key, inputs, plan_id=plan_id)
    return StructuredTool.from_function(
        coroutine=run, name=rec.key, args_schema=schema,
        description=f"{rec.description} (company tool, v{rec.current_version}, computes over the inputs you give it)")


async def generated_tools(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str) -> dict[str, StructuredTool]:
    return {r.key: _generated_tool(db, tenant_id, role_key, plan_id, r)
            for r in await builder.usable(db, tenant_id, role_key)}


def source_of(name: str, dyn_map: dict) -> str:
    from app.tools.web_tools import WEB_TOOLS
    if name in META_TOOLS:
        return "meta"
    if name in WEB_TOOLS:
        return "internet"
    if name.startswith("gen_"):
        return "generated"
    if name.startswith("mcp_"):
        return "mcp"
    if name in dyn_map:
        return "mcp" if name.endswith("_call_tool") or name.endswith("_discover_tools") else "integration"
    return "builtin"


def parallel_safe(name: str) -> bool:
    """No database session is used (web reads, chart building), so several may run at once."""
    from app.tools.web_tools import WEB_TOOLS
    return name in WEB_TOOLS or name == MAKE_CHART


async def execute(name: str, args: dict, runner, *, db: AsyncSession | None, tenant_id: str, role_key: str,
                  plan_id: str, label: str, source: str, record: bool = True,
                  mcp_integration: str | None = None, idempotent: bool = True) -> tuple[str, str | None]:
    """Run one read/compute call with recovery. Returns (result text, error category or None)."""
    from app.tools.dynamic_tool import is_tool_failure

    t0, retries, recovery = time.monotonic(), 0, []
    while True:
        try:
            result = str(await runner())
        except Exception as exc:  # noqa: BLE001 - a crashing tool is a failed call, never a crashed answer
            result = f"[TOOL ERROR] {name}: {type(exc).__name__}: {str(exc)[:300]}"
        cat = diagnostics.classify_error(result) if is_tool_failure(result) else None
        if cat and diagnostics.retryable(cat, idempotent=idempotent) and retries < diagnostics.MAX_RETRIES:
            await asyncio.sleep(diagnostics.BACKOFF_SECONDS[retries])
            retries += 1
            recovery.append(f"retry {retries} after {cat}")
            continue
        break
    if cat in ("not_found", "schema_mismatch") and mcp_integration and db is not None:
        try:
            from app.toolhub import mcp_sync
            res = await mcp_sync.refresh(db, tenant_id, mcp_integration, actor="recovery")
            recovery.append("refreshed the MCP tool list")
            result += (f"\n[RECOVERY] The server's tool list was refreshed ({res.get('tool_count', 0)} tools). "
                       "Check the tool name and arguments against the tool description and try once more.")
        except Exception as exc:  # noqa: BLE001
            recovery.append(f"tool list refresh failed: {type(exc).__name__}")
    if cat and (hint := diagnostics.advice(cat)):
        result += f"\n[WHAT IS NEEDED] {hint}"
    if retries and not cat:
        recovery.append("recovered")
    if record and db is not None:
        await metrics.record(db, tenant_id=tenant_id, tool_key=name, tool_label=label, tool_source=source,
                             role_key=role_key, plan_id=plan_id, status="success" if not cat else "failed",
                             error_category=cat, error_message=result if cat else None, retries=retries,
                             recovery="; ".join(recovery) or None, input_value=args, output_value=result,
                             duration_ms=int((time.monotonic() - t0) * 1000))
    return result, cat


ORCHESTRATION_RULES = """## Planning and tools
- For a complex request, break it into steps: which facts are needed, which tool gives each, what depends on what.
  Call independent tools in the SAME turn (they run in parallel where safe); call dependent ones after their inputs
  are available, passing real values from earlier results.
- Not sure a tool exists for something? Use find_tools. If a tool exists but is not granted to you, say an
  administrator can grant it — do not work around it.
- Use build_tool only for a calculation or data transformation that no existing tool or combination can do, and
  only after find_tools. Never use it to fetch data, contact anyone or change records.
- When numbers are compared, trend over time, form shares, show a distribution or are KPIs, add a chart with
  make_chart using exactly the numbers your tools returned (pick the type that fits: line for time, bar/hbar for
  comparisons and rankings, donut for shares of a whole, histogram for distributions, kpi for headline figures).
  Never write chart JSON or chart code in the answer text. No chart for simple conversational answers, and never a
  chart from numbers no tool returned. Say in the answer if data was insufficient for a chart.
- If a required integration is not connected or a tool fails, say what is missing; never fill gaps with guesses."""
