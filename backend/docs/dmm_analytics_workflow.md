# Digital Marketing Manager → Google Analytics 4 (task execution)

Representative workflow: *"How did our website traffic do over the last 7 days, and which
channels drove the most sessions?"*

## What happens

1. `POST /api/v1/agent/execute` (JWT; tenant and role come from the server, never the request).
2. **Readiness gate** (`services/task_readiness.py`, deterministic keywords, no LLM): the request
   needs Google Analytics. The gate checks, in order: a connected+enabled GA integration for the
   tenant → the role's `run_report` grant → (if no integration) the tenant's Google OAuth client
   settings. If anything is missing the request is saved as a **pending task**
   (`pending_tasks`), the user gets a truthful "setup needed" reply and the model is not asked to
   answer from memory.
3. **Admin-assisted setup** (admins see the actions, members are told to ask an admin):
   enter Google OAuth client ID/secret/redirect URI (stored encrypted per tenant; OAuth now reads
   them – previously only environment variables were read) → authorise with Google (read-only) →
   `POST /agent/pending-tasks/{id}/authorize` (admin only; grants only read-only, LOW-risk
   capabilities the task needs, to that role, audited).
4. `POST /agent/pending-tasks/{id}/resume` re-checks readiness and runs the **original request
   text**. A task closes only when its plan completes; a failed run stays open for retry.
5. **Execution**: planner → per-request dynamic tool → `Integration Manager.execute_capability`
   (tenant ownership, connected+enabled, role grant, decrypt in memory, provider call, discard) →
   audit row for every outcome (success, provider error, permission denial, timeout).
6. **Verification**: a failed call (`[INTEGRATION ERROR]`, `[PERMISSION DENIED]`, `[TIMEOUT]`, …)
   fails the plan with a plain reason and **no figures**. For a successful call every number in
   the model's answer is checked against the returned data (`services/grounding.py`); an answer
   with unsupported figures is replaced by the returned data. Totals/shares are computed in code,
   and a `Data source:` line (property and date range) is appended deterministically.

## GA4 provider behaviour
* Dates: `YYYY-MM-DD`, `today`, `yesterday`, `NdaysAgo` (resolved server-side).
* Property: optional when the account has exactly one; several → the AI asks which; IDs are
  validated as digits (no path injection).
* Discovery uses `accountSummaries` (the filter-less call; `properties.list` requires a filter).
* Google errors are mapped to readable, credential-free reasons (401 reconnect, 403 no
  access / API not enabled, 404, 429).

## What is verified, and how
`tests/test_marketing_analytics_e2e.py` runs the real app, planner, tools, grants, manager,
encryption, GA provider code and database. Only two boundaries are faked: **the LLM** and
**Google's HTTP APIs**. This proves our requests, permissions and honesty; it does **not**
prove behaviour against live Google. Live verification needs a Google Cloud project with the
*Google Analytics Data API* and *Google Analytics Admin API* enabled and the redirect URI
registered, then connecting a real GA4 property.

## Known limits
* Detection is keyword based; unusual phrasing of a GA question will not trigger the gate
  (the planner then has no GA tool and says so rather than inventing numbers).
* Other providers (GitHub, MCP, SQL) share the fixed tool bridge but have no readiness gate yet.
  (Search Console has one - see `seo_search_console_workflow.md`.)
