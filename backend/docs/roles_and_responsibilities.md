# Roles and responsibilities

This page describes the permission model that the code enforces. It adds no second permission system. Every row is
enforced on the server; the interface only reflects it.

## People (account roles)

The assignable roles are `Employee`, `Manager`, `Company Admin` and `AI Administrator`
(`app/services/team_service.py`). Company Admin, AI Administrator, `admin` and `superadmin` count as
**administrators** (`app/core/auth.py::is_admin_user`).

There is **no** separate "Technical / Operations Manager" or "Department Manager" account role. A department or
operations manager uses the `Manager` role. Its only extra permission over `Employee` today is reading documents with
the *Managers* access level.

| Capability | Employee | Manager | Administrator |
|---|---|---|---|
| Choose and switch their own AI employee workspace | yes | yes | yes |
| Chat with the selected AI employee; own saved conversations (History) | own only | own only | own only (cannot read other people's chats) |
| Read company knowledge | *All staff* documents | + *Managers* | + *Admins* |
| Upload / delete knowledge documents | no | no | yes |
| Ask an AI employee to do something that needs approval (creates a real approval request) | yes | yes | yes |
| See the approvals list | yes (read only) | yes (read only) | yes |
| **Approve or reject** an action; approve-and-resume a paused plan | no (403) | no (403) | yes |
| Connect / test / switch off / disconnect integrations; grant capabilities to AI employees | no | no | yes |
| Approved company profile | read | read | read and edit (audited) |
| Change EAAWP by asking any AI employee in plain words (company profile, AI employee settings, pause/resume, Marketplace modules, team invite/role/deactivate, access grants, switching off or disconnecting services, workflows, approval rules, notification emails) | no | no | yes — the exact changes are shown for approval first; nothing is saved before approval; the approving administrator is the one who makes the change |
| Workflows (scheduled work): create, edit, run, see run history | no | no | yes |
| Meeting Room: start a meeting | yes, sees own meetings | yes, sees own meetings | yes, sees all meetings |
| Internal messages | 1:1 with any active member; private to the two people | same | same (admins cannot read others' messages) |
| Team: invite, change role, deactivate | no | no | yes |
| Marketplace (activate AI employee modules), pause/resume AI employees, role configuration | no | no | yes |
| Audit log | no | no | yes |

## AI employees (built-in roles)

AI employees never approve anything. What they may **read**, **propose** and **execute** comes from the role's
saved configuration (`RoleConfiguration.tool_scopes_json`) and from capability grants on connected integrations.
The *Tools* dialog in the chat header shows the live list (`GET /api/v1/workspace/tools`).

| AI employee | Reads | Proposes (runs only after an administrator approves) | Executes without approval |
|---|---|---|---|
| Digital Marketing Manager | Campaign records and KPIs, funnel/strategy analysis, marketing knowledge, mapped company data, granted Google Search Console / Analytics / GitHub read capabilities | Send email, create/update campaign, create/update marketing objective | Draft email (no external effect), internal task, content briefs/ideas/drafts (saved internally, never published) |
| Data Analyst | Uploaded datasets (deterministic analysis engine), knowledge, granted database/integration reads | — (none configured) | Internal task, draft email |
| Institutional Clerk | Service requests the asker may see, procedures in knowledge | Update a service request's status | Draft a service document from an approved template, internal task |
| Medical Assistant | Appointment requests the asker may see, clinic information in knowledge | Update an appointment's status | — (never gives medical advice; emergencies are answered by a deterministic check before any model) |

Integration capabilities that write or are HIGH risk (for example GitHub *create issue / create pull request*) are
**never run by an AI employee**, even when they are granted. Medium-risk integration writes (some MCP tools) run when
granted, as before.

## How a role is enforced

1. **Which role answers.** An interactive chat request runs as the person's selected workspace. If the request names
   a different built-in role, it is refused with HTTP 409. Workflows, meetings and resumed pending tasks run as the
   role they were created for.
2. **Who the model is told it is.** Every model call starts with a role charter that the server builds from the
   role's configuration (`app/services/role_charter.py`). The charter covers identity, duties, limits, the other
   roles' jobs, honesty rules and formatting. The company's persona text is added after it. The model never sees a
   persona sent by the browser.
3. **What it can use.** Tools come from the server-side role configuration and grants. Approval-gated tools always
   create an approval request. On approval, the server re-checks the role's **current** configuration, the module
   and the pause state before it executes anything.
4. **What it may read.** Knowledge retrieval uses the role's own scope plus *Global / Shared* documents, never more
   than the asker could read. Conversation history is per person and per conversation, and a conversation belongs
   to one role. The Clerk and Medical roles never use shared agent memory.
5. **What it is told about the company.** It gets the administrator-approved company profile, as reference data
   only.

Limits: the model can still produce a wrong answer. The charter tells it to stay in role and to refuse other roles'
work, but whether it does so on every wording depends on the model. Tests cover what the server controls: the
charter on every call, role pinning and resistance to injection. A live check with the real model is part of the
testing guide.
