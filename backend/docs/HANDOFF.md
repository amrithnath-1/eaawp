# EAAWP handoff (keep updated; verify against the code, do not trust blindly)

Base branch: `master`. Never push/deploy without explicit approval. Nothing here claims live verification
unless stated.

## Status labels
IMPLEMENTED AND VERIFIED / IMPLEMENTED, MOCK-TESTED ONLY / IMPLEMENTED BUT NOT VERIFIED END TO END / PARTIAL / PLANNED / BLOCKED.

## Current state
| Area | Status |
|---|---|
| Tenant isolation, auth, route inventory (Phase 2) | IMPLEMENTED AND VERIFIED (test suite) |
| Universal AI Core: planner, tools, grants, audit, grounding (Phase 3) | IMPLEMENTED, MOCK-TESTED ONLY (fake LLM, fake Google) |
| GA4 workflow with setup/resume | IMPLEMENTED, MOCK-TESTED ONLY |
| Search Console workflow incl. property selection | IMPLEMENTED, MOCK-TESTED ONLY - live Google test pending the owner |
| Local runtime errors (CORS/500 on old DB) | IMPLEMENTED AND VERIFIED against the real server on an old-schema DB |
| Persistent workflows/scheduling, multi-agent, builder, other roles, knowledge, marketplace | PLANNED (see roadmap) |

## Run / test
* Backend tests: `cd backend; python -m pytest -q` (venv with `requirements`). Frontend: `npx tsc --noEmit`, `npm run build`.
* Windows run + migration steps: `docs/local_windows_runtime.md`.
* Migration head: `w0x4y59z1a17`. Rehearse any migration on a copy first.

## Architecture pointers
* Tool bridge: `app/tools/dynamic_tool.py` -> `app/integrations/manager.py` (`execute_capability`: tenant, status, role grant, decrypt in memory).
* Readiness gate + pending tasks: `app/services/task_readiness.py`, `app/api/routers/pending_tasks.py`.
* Grounding: `app/services/grounding.py`. Errors/CORS: `app/core/error_handlers.py`. Schema check: `app/core/schema_check.py`.
* Docs: `dmm_analytics_workflow.md`, `seo_search_console_workflow.md`.

## Security constraints
Tenant from verified auth only; model is never the authorization authority; secrets never to LLM/logs/chat;
no wildcard CORS; read-only by default; one-click approvals only for LOW-risk read capabilities.

## Next
Phase A done after merge -> live-verify Search Console (owner) -> Phase D (persistent workflows/scheduling).
