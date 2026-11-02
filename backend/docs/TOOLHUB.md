# Tool hub — discovery, orchestration, Tool Builder, diagnostics, metrics, charts

One shared system for every AI employee. Nothing is role-specific except the grants and two role limits
(the Medical Assistant gets neither the internet tools nor build_tool).

## Architecture (what exists and where)

```
chat message ──► execute_agent (execution.py) ──► run_chat_agent (services/chat_agent.py)
                                                     │  tools offered = role config + integration grants
                                                     │                + MCP per-tool grants + generated-tool grants
                                                     │                + internet tools + find_tools/build_tool/make_chart
                                                     ▼
            model decides each step ──► toolhub/orchestration.execute()   (read / compute calls)
                                         ├ diagnostics.classify_error → bounded retry (idempotent only)
                                         ├ MCP not_found/schema_mismatch → mcp_sync.refresh
                                         ├ metrics.record → toolhub_executions
                                         └ parallel_safe calls of one round run concurrently
                                      ──► action_governance (actions: approval / never retried)
            make_chart ──► toolhub/charts.build (verified against tool results) ──► response.charts ──► chat + History
            build_tool ──► toolhub/builder (assess → generate → validate in sandbox → register → grant requester)
MCP TEST NOW / Review tools ──► integrations/manager ──► toolhub/mcp_sync.sync (registry + snapshot + events)
Tool Center (/tools) ──► api/routers/toolhub.py (admins)
```

| Module | Responsibility |
|---|---|
| `db/toolhub_models.py`, migration `f5a0b27c8d46` | `toolhub_tools`, `toolhub_tool_versions`, `toolhub_tool_grants`, `toolhub_executions`, `toolhub_mcp_snapshots`, `toolhub_events` (all tenant-scoped, indexed; additive migration) |
| `toolhub/risk.py` | six risk classes from every word of a tool name, and the policy for each |
| `toolhub/schema.py` | JSON-schema validator (the subset tool schemas use) |
| `toolhub/diagnostics.py` | error categories, which are retryable, backoff, "what is needed" advice |
| `toolhub/metrics.py` | execution records (secret-scrubbed summaries), per-tool stats, reliability hints |
| `toolhub/mcp_sync.py` | discovery → registry: added / changed (schema hash) / removed; snapshots; audit |
| `toolhub/sandbox.py`, `_sandbox_runner.py` | static code checks + isolated `python -I -S -B` child with empty env and rlimits |
| `toolhub/builder.py` | reuse assessment, generation, validation, bounded correction, registration, versions, rollback, grants, run |
| `toolhub/orchestration.py` | meta tools, generated tools as callable tools, the recovering executor, parallel safety |
| `toolhub/charts.py` | chart specs from verified data, automatic type |
| `api/routers/toolhub.py` | Tool Center API (see TOOLHUB_API.md) |
| `src/routes/tools.tsx`, `src/components/eaawp/ChatChart.tsx` | Tool Center UI, chart rendering + PNG export |

## Risk classes and policy

| Class | Examples | Policy |
|---|---|---|
| read_only | list_sites, firecrawl_scrape | automatic when the role is granted |
| internal_compute | generated tools, calculate_* | automatic |
| internal_modify | create_*, update_* | existing governance (approval where configured) |
| external_comm | send_*, post_*, publish_* | approval; MCP tools of this class never run from chat |
| financial | pay, charge, refund | explicit approval; MCP tools never run from chat |
| security_sensitive | grant, token, admin, password | blocked for AI employees |

## Recovery (what is and is not done)

- Retried: timeouts, rate limits (429), unavailable (5xx/connection) — only for idempotent read/compute calls,
  at most 2 retries (0.5 s, 1.5 s).
- Refreshed: an MCP tool reported missing or with a changed schema → tool list rediscovered, model told to retry.
- Reported with what is needed (never bypassed): authentication, permission, approval, provider limits.
- Never retried: actions (anything through governance), invalid arguments (the model is shown the error instead).
- The system cannot repair an external MCP server; it records the failure and says so.

## Sandbox guarantees and limits

- Static: only `run(inputs)`, helpers and constants; imports from math, statistics, json, re, datetime, decimal,
  fractions, collections, itertools, functools, string, operator, heapq, bisect, textwrap, calendar, unicodedata,
  random; no names/attributes starting with `_`, no text containing `__`, no eval/exec/open/getattr/format/
  attrgetter/methodcaller/classes/async.
- Process: empty environment, empty temp working directory, restricted builtins + import hook, CPU 3 s, memory
  512 MB, no file writes, ≤16 open files, no child processes, 6 s wall clock, 1 MB output.
- Limits: the OS-level limits apply on Linux/macOS (Render); on Windows only the timeout and static checks apply.
  There is no kernel network namespace — network access is prevented by the import allowlist and the static checks.

## Least privilege

Discovering an MCP tool grants nothing. A generated tool is granted only to the AI employee role that asked for it;
other roles need an administrator's grant (Tool Center → Registry, or by asking in chat). Grants, revokes,
deactivation and rollback are audited (`toolhub_events`).
