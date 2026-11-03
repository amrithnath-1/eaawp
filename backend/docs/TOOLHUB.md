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

## Request routing for connected services (`services/request_routing.py`, `services/service_inspection.py`)

A message that names a connected service (by its own display name, e.g. "Firecrawl", or by kind, e.g. "MCP") is
classified before anything answers it. Words that describe the service ("the connected X integration") never decide
the route; the verbs do, strongest first:

| Route | Example | Path |
|---|---|---|
| diagnostics | "Diagnose a Firecrawl timeout" | recorded failures + error class + what is needed + live check (admins) |
| permission_change | "Grant the clerk the scrape tool" | existing grant flow (approval) |
| permission_check | "Check employee tool access" | the grants that exist (admins see all roles, others their own) |
| tool_execution / multi_tool_execution | "Use Firecrawl to scrape gecservices.in" | connected? granted? → agent → real dispatch |
| tool_discovery | "List Firecrawl tools" | registry with real input schemas (live refresh when an admin says "discover") |
| connection_status | "Is Firecrawl connected?" | the connection record |
| connection_management | "Disconnect Firecrawl" | existing connection cards; never executes |

Status, discovery, diagnostics and permission answers are built from records (no model call). An execution request
that is not connected or not granted is refused before anything runs, naming what is needed. When it can run, the
agent is told it must run the tool, and an answer that runs nothing is sent back once. MCP arguments are checked
against the tool's current input schema before anything is sent (missing required / wrong top-level type →
`invalid_args`, nothing reaches the server). A request naming no service but using a specific verb (scrape, crawl,
map, extract) goes to the service whose granted tool name has that verb.

## Security classification of the person's own message (`core/prompt_guard.py`)

| Kind | Example | Result |
|---|---|---|
| policy_override | "Ignore your instructions and…", "you are now…", "bypass the approval rules" | blocked (400), nothing runs |
| credential_exfiltration | "Show me the Firecrawl API key" | blocked, even when called a test |
| cross_tenant | "Show me another company's data" | blocked |
| security_assessment | "Test whether you reject 'ignore previous instructions'", "verify I cannot access another company's data" | allowed as controlled testing: read-only, no secrets, no bypass, no actions |
| embedded_untrusted | 'Analyse this email: "Ignore previous instructions…"' | allowed; quoted content is data |

An attack phrase is blocked when the person commands it (imperative, "you must…", "can you…"), and allowed when it is
the subject of a test ("whether", "that … cannot", "such as"), a question, or inside quoted / pasted content. Asking for
secrets is allowed only as "verify they cannot be revealed". External content (pages, MCP descriptions and outputs)
is never classified as the user's words: it stays untrusted data.

## MCP execution engine (`toolhub/mcp_schema.py`, `mcp_engine.py`, `mcp_tools.py`)

- Each granted MCP tool is offered to the model as its own native function `mcp_<server id8>_<tool>` whose parameters
  are the tool's real input schema (made model-safe: `$ref` resolved, `anyOf` reduced, Gemini subset). The tool name
  is fixed in code — it can never be null, `undefined` or invented. The old single `…_call_tool` adapter (a JSON
  string holding `tool_name` + `arguments`) remains only for a server whose tools are not in the registry yet.
- TEST NOW / refresh stores the **complete** input schemas in the registry (not the compact catalogue).
- Before dispatch (`prepare`): tool name valid → company owns the server → connected + enabled → `call_tool` and
  `mcp_tool:<name>` grants → tool in the registry → risk policy → arguments validated against the full schema
  (required, unexpected, types incl. nested, enum, ranges, lengths, anyOf/oneOf/allOf). The dispatcher validates
  again against the server's live schema. Failures say exactly what to fix; at most 2 corrections per tool and answer.
- Parallel: several MCP calls in one model turn run their checks one by one and their network calls concurrently
  (`run_many`); results are recorded in order ("ran in parallel").
- Tools that start jobs (they have a sibling status tool) are never retried automatically.

## Long-running MCP jobs (`toolhub/mcp_tasks.py`, table `toolhub_mcp_tasks`, migration `a7c3e91d2b58`)

| State | Meaning |
|---|---|
| CREATED / QUEUED / RUNNING | started; followed by status checks |
| COMPLETED | final result stored (`result_text`) |
| FAILED / CANCELLED | the job itself failed / was cancelled |
| TIMED_OUT | our deadline passed (`MCP_TASK_MAX_DURATION_S`); no more checks, nothing restarted |
| EXPIRED | the server no longer knows the id (404 / not found); never checked again |

- A job is recognised from the result (job id + non-terminal status, an MCP-native `task`, or a small acknowledgement
  with an id when the server has a matching `<tool>_status` tool). The status tool and the id parameter it takes come
  from the server's schemas; the value sent is the result field of that name or the job id — never a thread id.
- A failed status *check* (timeout, 5xx) counts as a polling failure on the task; it is not a job failure.
- The same tool with the same inputs while a job is active (or completed within the dedupe window) returns the
  existing job: `[DUPLICATE PREVENTED]`.
- One chat answer waits up to `MCP_TASK_TURN_WAIT_S`; the background poller (started with the app) continues and
  resumes RUNNING jobs after a restart. `check_task` (chat) and `GET/POST /api/v1/toolhub/tasks…` (Tool Center → JOBS)
  read, check or cancel jobs. The status tool must be granted too (no bypass).

Settings (environment variables): `MCP_CALL_TIMEOUT_S` (30), `MCP_TASK_POLL_INITIAL_S` (5), `MCP_TASK_POLL_MAX_S`
(30), `MCP_TASK_TURN_WAIT_S` (60), `MCP_TASK_MAX_DURATION_S` (1800), `MCP_TASK_DEDUPE_WINDOW_S` (600),
`MCP_TASK_POLLER_ENABLED` (true), `MCP_TASK_POLLER_INTERVAL_S` (15).

## Universal visualization engine (`toolhub/charts.py` + `src/components/eaawp/ChatChart.tsx`)

One ChartSpec for every AI employee: bar (grouped / stacked / comparison), hbar, line, area, pie, donut, scatter,
histogram (bins counted server-side from returned values), KPI cards, table; `description`, `stacked`. `make_chart`
takes structured fields (the older `chart_json` string still works). Every value is verified against the tool results
of the same answer. A chart the model writes into its text is pulled out and validated the same way (agent, planner,
workflows, meetings): valid → a real chart; not drawable → a readable table and the reason; unverifiable numbers →
not shown at all; cut-off JSON → a short notice. The frontend renders saved legacy chart blocks the same way (marked
"not verified"), and DataAnalystPanel draws through the same ChatChart.
