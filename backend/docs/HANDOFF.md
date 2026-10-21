# EAAWP handoff (keep updated; verify against the code, do not trust blindly)

Base branch: `master`. Never push/deploy without explicit approval. Nothing here claims live verification
unless stated.

## Phase G: Data Analyst (branch feat/phase-g-data-analyst)
- Dataset upload, deterministic analysis engine, NL questions (LLM plans, engine computes), saved reports + CSV export, `/data` page, agent tools `list_datasets`/`analyze_dataset`, `DATA_INTELLIGENCE_ANALYST` role now implemented. See `docs/data_analyst.md`. Migration `a4b8c93d5e21`. Status: IMPLEMENTED, MOCK-TESTED; browser-exercised on a real server with a scripted LLM.

## Phase F: AI Employee Builder (branch feat/phase-f-employee-builder)
- Approved employees become real roles; versioned NL revisions with approval; rollback; pause. See `docs/employee_builder.md`. Migration `z3a7b82c4d20`. Status: IMPLEMENTED, MOCK-TESTED; browser-exercised with a scripted LLM.

## Phase E: Meeting Room (branch feat/phase-e-meeting-room)
- Real multi-agent delegation + persistent Meeting Room: `docs/meeting_room.md`. Migration `y2z6a71b3c19` (3 new tables). Status: IMPLEMENTED, MOCK-TESTED; UI exercised in a real browser against a real server with a scripted LLM only.
- `execute_agent` now honours `blueprint.role_key` (only for roles the company has) and plans when a role's only tools are granted integrations.

## Phase D hardening (branch fix/phase-d-hardening)
- Retry guard (`side_effects_may_have_happened`), real cancellation (plan rejected / pending task cancelled), admin-only run history. Tests: `TestHardeningRetriesCancellationAndHistory`.
- Migration chain rehearsed from `u8v2w37x9y15` with data to `x1y5z60a2b18` and back one step.
- NOT proven: real Search Console reports on a production schedule need an authorized integration and an end-to-end test.

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
| Phase D: persistent workflow runs, schedules, retries, recovery (`docs/workflows_scheduling.md`) | IMPLEMENTED, MOCK-TESTED ONLY (fake LLM/Google); scheduler loop + crash recovery also exercised on a real uvicorn process (no live Google) |
| Meeting Room (E), AI Employee Builder lifecycle (F), Data Analyst (G) | IMPLEMENTED, MOCK-TESTED ONLY (scripted LLM; real server + browser exercised) |
| Institutional Clerk, Medical Assistant, invitations/messaging, knowledge/DB connectivity, marketplace | PLANNED (see roadmap) |

## Run / test
* Backend tests: `cd backend; python -m pytest -q` (venv with `requirements`). Frontend: `npx tsc --noEmit`, `npm run build`.
* Windows run + migration steps: `docs/local_windows_runtime.md`.
* Migration head: `a4b8c93d5e21`. Rehearse any migration on a copy first.

## Architecture pointers
* Tool bridge: `app/tools/dynamic_tool.py` -> `app/integrations/manager.py` (`execute_capability`: tenant, status, role grant, decrypt in memory).
* Readiness gate + pending tasks: `app/services/task_readiness.py`, `app/api/routers/pending_tasks.py`.
* Grounding: `app/services/grounding.py`. Errors/CORS: `app/core/error_handlers.py`. Schema check: `app/core/schema_check.py`.
* Docs: `dmm_analytics_workflow.md`, `seo_search_console_workflow.md`.

## Security constraints
Tenant from verified auth only; model is never the authorization authority; secrets never to LLM/logs/chat;
no wildcard CORS; read-only by default; one-click approvals only for LOW-risk read capabilities.

## Next
Phases A and D merged locally -> owner live-verifies Search Console -> Phase E (multi-agent workforce / Meeting Room backend).
