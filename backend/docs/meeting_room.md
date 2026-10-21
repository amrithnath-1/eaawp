# Meeting Room - multi-agent delegation (Phase E)

**Status:** IMPLEMENTED, MOCK-TESTED (scripted LLM + fake Google) and exercised through the real
UI / HTTP / database. NOT verified with a live LLM or live Google in this sandbox.

## What it does
1. A user (any member) states an objective: `POST /api/v1/meetings`.
2. A **coordinator** (LLM) splits it into <= 6 tasks and assigns each to one of the company's AI roles
   (built-in roles are created on first use; company-specific roles are included; other companies' roles never are).
   Dependencies only point backwards (no cycles). If the model is down or answers badly, the whole objective goes to
   the Digital Marketing Manager and the meeting says so.
3. Tasks run **in dependency order**. Each runs through the same governed pipeline as normal chat
   (`execute_agent`: server-side role config, integration grants, readiness gate, approvals) as the meeting's creator.
   A finished task's result is handed to the tasks that depend on it - this is the agent-to-agent delegation.
4. Every delegation, result, pause and the final summary is a stored message. The summary is built from stored results only.

## Guarantees (each covered by a test that fails if the guarantee is removed)
- A task never runs unless all its dependencies completed; dependents of a failed task are `skipped`.
- Cancel: queued meeting never starts; a running meeting stops before the next task; a pending approval plan is rejected
  so it can no longer execute; a pending setup task is cancelled.
- Pause: an agent needing approval/setup pauses the meeting (`awaiting_approval` / `waiting_setup`);
  `resume` never repeats completed tasks and is refused while an approval is still undecided.
- The creator is re-validated before every task (deactivated / moved company => the rest is skipped).
- Visibility: creator and company administrators only; other companies and other members get 404.
- A task executes with ITS role's grants (a finance-only Search Console grant works for the finance role and not for marketing).
- Startup recovery fails meetings left `running` > 30 min; nothing is auto-retried (no duplicate external actions).

## API
`GET/POST /api/v1/meetings`, `GET /{id}`, `POST /{id}/messages` (follow-up work), `POST /{id}/cancel`, `POST /{id}/resume`.
Frontend: `/meeting` (`MeetingRoomPanel.tsx`) polls every 2 s while agents work.

## Known limits
- Built-in roles other than the Digital Marketing Manager have no tools/persona yet (they reason only); the AI Employee Builder (Phase F) is what creates fully configured roles.
- Tasks run sequentially (no parallel branches).
- A live LLM may produce different plans; the validator rejects unusable ones, but plan quality is unproven.
