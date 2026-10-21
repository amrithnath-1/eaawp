# EAAWP handoff (keep updated; verify against the code, do not trust blindly)

Base branch: `master`. Never push/deploy without explicit approval. Nothing here claims live verification
unless stated.

## Phase J (part 3): Authorized invitation email (branch feat/phase-j-invite-email)
- Optional emailing of an invitation link on explicit admin action via the company's SMTP integration (invitee address only, fixed template, allowed-origin link, 20/hour cap, safe audit). Fixed pre-existing 500 when re-saving an SMTP config. See `docs/team_invitations.md`. No migration. Status: IMPLEMENTED, MOCK-TESTED + exercised against a local SMTP server; NOT verified with a real mail provider.

## Phase K (part 1): Database connectivity hardening (branch feat/phase-k-connectivity)
- Column-level blocking (sensitive names auto-blocked), outbound-host SSRF guard, connected-state check, failure-audit fix, connection-edit 500 fix, new `/connections` admin page (databases + SMTP; they were unreachable in real mode). Verified against a REAL PostgreSQL 16 (8 live tests, skipped without `EAAWP_TEST_PG_*`) and through the UI. See `docs/database_connectivity.md`. Migration `f9a3b48c0d56`. MySQL, MCP and knowledge-base NOT verified in this part.

## CURRENT STATE (updated after resuming; supersedes the earlier pause checkpoint)
- **Branch:** `master` (local). **Last code commit:** `cd3bfcb` (Phase K part 1). Nothing pushed/deployed; 13 local commits ahead of origin/master by the hook's count (push needs the owner's explicit approval).
- **Completed (MOCK-TESTED ONLY unless noted):** phases A-J3 (see sections below). J3 invitation email was also exercised against a real local SMTP server; no real mail provider yet.
- **Test results at `7382ea0`:** full backend suite `2119 passed, 5 skipped, 0 failed` (incl. 8 live-PostgreSQL tests); frontend build + tsc clean; real-browser runs for G-J3 with a scripted LLM.
- **Migration head:** `e8f2a37b9c45` (J3 added no migration). Owner's local DB not migrated by me; back up and rehearse on a copy first.
- **Known gaps:** no live LLM / Google call; agent memory retrieval broken for all roles (pre-existing); medical/message data unencrypted at rest; messaging is polling; no automatic notification emails.
- **Next:** Phase K part 2 (MySQL verification if a server is available; MCP user flow; knowledge-base verification), L (marketplace/entitlements/module activation), M (responsive UI, notifications, activity history, production readiness, Windows install docs). Per phase: branch -> backend+frontend+migration+tests -> mutation checks -> browser run -> full suite -> commit with trailers -> `git merge --ff-only` into master -> HANDOFF + report.

## Phase J (part 2): Internal messaging (branch feat/phase-j-messaging)
- 1:1 messages between active members of a company, private to the two participants (admins cannot read them), unread badge, `/messages` page. See `docs/internal_messaging.md`. Migration `e8f2a37b9c45`. Status: IMPLEMENTED, MOCK-TESTED ONLY. Polling, no push/email notification, no groups/attachments.

## Phase J (part 1): Team invitations + members (branch feat/phase-j-invitations)
- Single-use expiring hashed invitation links, accept page (`/accept-invite`), `/team` admin page (invite, resend, revoke, change role, deactivate/reactivate with token revocation). See `docs/team_invitations.md`. Migration `d7e1f26a8b34`. Status: IMPLEMENTED, MOCK-TESTED ONLY. No email delivery yet (part 3); internal messaging is part 2.

## Phase I: Medical Assistant (branch feat/phase-i-medical-assistant)
- Deterministic emergency/crisis/advice guard before the model, appointment requests + staff queue + verbatim-grounded intake summary, `MEDICAL_ASSISTANT` role (read tools + approval-gated status update), never stored in shared memory, `/clinic` page. See `docs/medical_assistant.md`. Migration `c6d0e15f7a23`. `execute_agent`: guarded-only action tools now count as action tools (affects all roles). Status: IMPLEMENTED, MOCK-TESTED ONLY. Data is unencrypted at rest (documented).

## Phase H: Institutional Clerk (branch feat/phase-h-institutional-clerk)
- Service requests + review workflow + timeline, templated documents (draft/issue/void with serials), extraction from uploads, `INSTITUTIONAL_CLERK` role with identity-aware read tools and two governed actions. See `docs/institutional_clerk.md`. Migration `b5c9d04e6f22`. Tool context now carries `user_id`/`is_admin`. Status: IMPLEMENTED, MOCK-TESTED; two-user browser flow exercised on a real server with a scripted LLM.

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
| Institutional Clerk (H) | IMPLEMENTED, MOCK-TESTED ONLY (scripted LLM; real server + browser exercised) |
| Medical Assistant (I) | IMPLEMENTED, MOCK-TESTED ONLY (scripted LLM; unencrypted at rest) |
| Team invitations + member admin (J1) | IMPLEMENTED, MOCK-TESTED ONLY (no email delivery) |
| Internal messaging (J2) | IMPLEMENTED, MOCK-TESTED ONLY (polling; no notifications) |
| Authorized email, knowledge/DB connectivity, marketplace | PLANNED (see roadmap) |

## Run / test
* Backend tests: `cd backend; python -m pytest -q` (venv with `requirements`). Frontend: `npx tsc --noEmit`, `npm run build`.
* Windows run + migration steps: `docs/local_windows_runtime.md`.
* Migration head: `f9a3b48c0d56`. Rehearse any migration on a copy first.

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


## Phase K (part 2): knowledge base access control (branch feat/phase-k-knowledge)
Status: IMPLEMENTED, MOCK-TESTED ONLY (embedder faked; no live Gemini). See docs/knowledge_base.md.
- Fixed: document `access_level` was stored but never enforced; `/retrieve` honoured client `role_scope`, required an OpenAI key, listings leaked restricted document names, agent tool printed blank source names, no text-size cap, unvalidated `role_scope`.
- Tests: tests/test_knowledge_access.py (19), 7 mutations killed.
- Still open: MCP user flow, MySQL, Phase L, Phase M.

## CURRENT STATE (updated 2026-10-21 ~22:30 IST)
- Latest code commit: 6a9fdfd (Phase K2), merged to local master; 17 commits unpushed (nothing pushed/deployed without explicit approval).
- Full suite: 2130 passed, 13 skipped (8 skipped = real-PostgreSQL tests, need EAAWP_TEST_PG_* env).
- Completed: A-K2 (see per-phase sections). Current task: Phase L (marketplace/entitlements/module activation) not yet started.
- Next action: Phase L, then MCP user flow, then Phase M. Progress dashboard (Claude artifact) mirrors this file.
