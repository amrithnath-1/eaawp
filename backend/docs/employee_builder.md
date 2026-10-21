# AI Employee Builder (Phase F)

**Status:** IMPLEMENTED, MOCK-TESTED (scripted LLM) and exercised in a real browser against a real server (scripted LLM only). Not verified with a live LLM.

1. **Build** (`POST /employees/build`, admin): plain-language request -> proposal. Unknown tool keys are removed and reported; send/create/update tools are forced to "needs approval".
2. **Approve** (`POST /employees/blueprints/{id}/approve`): creates the employee, **writes its role configuration** (what `execute_agent` and the Meeting Room use), and records version 1. A colliding role key gets a suffix - an existing role is never overwritten. Persona injection wording is replaced.
3. **Change in plain language** (`POST /employees/{id}/revise`): the model proposes a change; it is validated and stored as a *proposed* version with a field-by-field diff. Nothing applies until `.../versions/{n}/approve`. `role_key` can never change. A newer proposal replaces an open one.
4. **Rollback** (`.../versions/{n}/rollback`): appends a NEW version copying an old snapshot (re-validated under today's rules); history is never edited.
5. **Pause** (`POST /employees/{id}/pause`): a paused employee gets 403 from `/agent/execute`, is excluded from the Meeting Room roster; resume restores it. Built-in roles with no employee record are unaffected.

All lifecycle endpoints are administrator-only and tenant-scoped (other company => 404); each change is audited.
Frontend: `/employees` (EmployeeBuilderPanel + EmployeeDetailPanel).
Builder-created roles are changed only through versions; direct `PUT/PATCH /roles/{key}` still applies to built-in roles only.

## Limits
- Integration grants are NOT part of an employee: after approval an administrator still grants each capability explicitly (the proposal lists what is missing).
- Tools available are those in the platform's tool registry; a role's real power also depends on integrations granted to it.
