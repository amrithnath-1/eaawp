# Plan — MCP reliability, dynamic tool execution, universal visualization (2026-11-03)

## Execution flow as found (inspected, not assumed)

```
chat → execute_agent (api/routers/execution.py)
     → get_available_tools + build_dynamic_tool_adapter (tools/dynamic_tool.py)   one LangChain tool per GRANT:
         MCP server → ONE tool "integration_<id8>_call_tool" whose only input is params_json: a JSON *string*
         {"tool_name": ..., "arguments": {...}}; per-tool inputs appear only as prose in its description
     → run_chat_agent (services/chat_agent.py): model calls tools, orch.execute (toolhub/orchestration.py) runs them
     → manager.execute_capability → MCPIntegrationProvider._call_tool (live tools/list, my schema check, tools/call)
     → text result → model → final text
charts: model may call make_chart(chart_json: JSON *string*) → charts.build (verified vs tool output)
     → turn_charts contextvar → response.charts → cabin.tsx → ChatCharts (recharts)
```

## Root causes

| Observed | Root cause |
|---|---|
| Missing required `objective`; arguments not matching the schema | The model never sees the tool's schema as a function signature: one generic call_tool per server takes a JSON string; required fields are prose. Gemini's function calling cannot enforce what it is not given. |
| `tool_name` null / invalid | Same: `tool_name` is a field inside a JSON string the model writes by hand; nothing structural forces it. |
| Async job: thread ID polled → timeout → 404, result lost | firecrawl_agent returns a job `id` AND a separate `threadId`; firecrawl_agent_status takes `id` (server source, firecrawl-mcp 3.36). The model polled with the thread ID (404). Nothing in EAAWP knows a call started a job: no job record, no poller, no state, no dedupe — a timed-out poll is just text, and the model may start the job again. |
| "Parallel" MCP calls | Only DB-free tools (web, make_chart) run concurrently; every MCP call is sequential because it shares the request's DB session. |
| Raw chart JSON in chat | Charts reach the UI only through make_chart, whose input is a JSON string. When the model writes the chart object into its answer instead (or after make_chart refuses it), the backend passes it on as text and the UI renders it as a code block. The planner path (workflows, meetings, agent fallback) has no chart path at all. |
| Separate chart systems | DataAnalystPanel draws its own recharts; chat uses ChatChart. |
| Streaming | There is no streaming (request/response). The risk is only a half-written JSON block in a final message — handled by the same extraction. |

## Changes (file ownership)

Backend — MCP
1. `toolhub/mcp_schema.py` (new): JSON-schema → model-safe function schema (Gemini subset), required/optional/types/nested/enum
   summary for descriptions, full server-side validation (required, unexpected keys when additionalProperties:false,
   types incl. nested objects/arrays, enum, min/max, lengths; anyOf/oneOf = any branch).
2. `toolhub/mcp_engine.py` (new): prepare (DB: tenant, connected, enabled, grants, credentials in memory) → dispatch
   (network only; parallel-safe) → finish (audit, metrics, job detection). Rejects missing/invalid tool names before
   anything. Bounded correction: validation errors go back to the model with the schema; ≤2 corrections per tool/turn.
3. `toolhub/mcp_tasks.py` (new) + `db/toolhub_models.McpTask` + additive migration: lifecycle CREATED/QUEUED/RUNNING/
   COMPLETED/FAILED/TIMED_OUT/EXPIRED; detects job-start results generically (id field + non-terminal status / "returns
   a job ID"); finds the server's status tool and its id parameter from the live schemas (never assumes threadId);
   polls with exponential backoff, a per-turn wait and a max duration; 404/unknown id → EXPIRED, never polled again;
   status-call failures counted separately from tool failures; duplicate start (same tool + args, active or recent) →
   existing task returned; cancel via the server's cancel tool when it has one; MCP-native tasks (result.task) via
   tasks/get + tasks/result; background poller resumes RUNNING tasks after a restart.
4. `services/chat_agent.py`: each granted MCP tool becomes its own native function with its real schema
   (`mcp_<id8>_<tool>`, tool name fixed in code); real parallel MCP dispatch; `check_task` meta tool.
5. `api/routers/toolhub.py`: GET /toolhub/tasks, POST /toolhub/tasks/{id}/cancel (admin), tasks in Tool Center.
6. Registry refresh: schema mismatch / not found → mcp_sync.refresh (exists) and the native tools are rebuilt.

Backend — visualization
7. `toolhub/charts.py`: one ChartSpec for all roles; types bar, hbar, line, area, pie, donut, scatter, histogram,
   kpi, table; options stacked, grouped (multi-series), description; histogram bins computed server-side from raw
   values; `extract_from_text()` — chart objects written into an answer are pulled out, validated like make_chart,
   and either become charts or a readable table + reason (never raw JSON).
8. `toolhub/orchestration.py`: make_chart takes structured fields (legacy chart_json still accepted).
9. `api/routers/execution.py`: extraction applied to every path (agent, planner, simple) so workflows and meetings
   never show chart JSON; charts returned in the response contract (unchanged field `charts`).

Frontend
10. `lib/charts.ts`, `components/eaawp/ChatChart.tsx`: new types/options, description, empty/error states,
    fallback table; `ChatMarkdown` renders legacy saved messages' chart blocks as charts (validated) or tables.
11. `DataAnalystPanel.tsx`: uses the shared ChatChart (analysis result → ChartSpec).

Tests: unit (mocked MCP responses), integration (real local MCP servers incl. an async-job server), frontend unit +
Playwright screenshots (light/dark/mobile), full regression. Live Firecrawl only where reachable (not from this sandbox).

Migration: one additive table (toolhub_mcp_tasks). No existing table or row is changed.
