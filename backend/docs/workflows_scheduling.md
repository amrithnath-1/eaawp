# Workflows and scheduling (Phase D)

## Model
* `workflows` (existing) gained run settings: `role_name` (the AI role it runs as), `run_as_user_id`
  (the administrator who last saved it - taken from the login, never from the request body),
  `timezone` (IANA zone the cron is read in), `max_retries` (0-5, default 0), `retry_delay_minutes`.
* `workflow_runs` (new, migration `x1y5z60a2b18`): one row per attempt. `UNIQUE(workflow_id, slot)`
  is the duplicate-run guard. Statuses: queued, running, completed, failed, awaiting_approval,
  waiting_setup, skipped, cancelled. Rows hold no credentials or tool output (a 300-char summary).

## Execution path (one for manual and scheduled runs)
`services/workflow_runner.py` -> `execute_agent` (the same function chat requests use) -> readiness
gate -> role tool list -> capability grants -> planner -> approvals -> grounded answer.
Nothing about authorisation is re-implemented; the previous hard-coded tool list and made-up role
names (which meant integration tools such as Search Console could not run on a schedule) are gone.

## Guarantees and how they are tested (`tests/test_workflow_reliability.py`)
| Guarantee | Mechanism |
|---|---|
| No duplicate scheduled run (ticks, parallel workers, restarts) | unique slot claim; conditional `queued -> running` update |
| Permissions re-checked on EVERY run | workflow enabled, company active, owner exists in the tenant, is active and is still an admin; then role grants / credentials by the normal path |
| Missing setup never guesses | run = `waiting_setup`, a pending task is saved for the owner, workflow released; next slot retries |
| Honest outcomes | only a completed plan is `completed`; failures keep a plain reason |
| Explicit retries | per-workflow limit and linear backoff; only `failed` is retried (not setup/approval/skip) |
| Crash/restart recovery | runs `running` > 20 min -> `failed (Interrupted)`, workflow released, retry queued if allowed; also runs at startup |
| Approval pauses | when the plan's approval is decided, the run and workflow get the real outcome |
| Tenant isolation | history/cancel are tenant-scoped; admin-only mutations |
| Time zones | cron evaluated in the workflow's zone |

## Behaviour to know
* Cron subset is unchanged: five fields, `*`, `*/n`, single numbers; **weekday 0 = Monday**.
* Missed schedules during downtime are **not** replayed (no catch-up storm).
* The scheduler is still an in-process loop (60 s tick). Duplicate protection is database-level, so
  running several backend processes is safe, but a dedicated worker/queue is a production-hardening
  item (Phase M).
* Notifications: each finished run writes an audit-log entry. Email/in-app push is PLANNED.

## Status
| Part | Status |
|---|---|
| Run history, unique-slot de-duplication, re-validation, retries, recovery, cancel, timezone | IMPLEMENTED, MOCK-TESTED ONLY (fake LLM, fake Google, injected clock) |
| Behaviour in a long-running real process / over a real restart | IMPLEMENTED BUT NOT VERIFIED END TO END |
| Notifications beyond audit entries | PLANNED |
