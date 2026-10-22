# AI employee workspaces (post-registration role selection)

Every person works with one AI employee at a time: **Digital Marketing Manager**, **Institutional Clerk**,
**Medical Assistant** or **Data Analyst**. The choice is stored on the server per user (table `user_workspaces`,
one row per user, tenant-scoped) and decides:

| Aspect | Source |
|---|---|
| Navigation | `GET /api/v1/workspace` -> `navigation` (role entries + shared entries + admin entries for administrators) |
| Dashboard (`/workspace`) | role-specific: marketing overview, clerk requests, clinic appointments, analyst datasets/reports |
| AI instructions, tools, quick prompts | the company's own `RoleConfiguration` for that role (seeded from defaults on first selection) |
| Knowledge retrieval | `role_scope` = the role key: Global documents + the role's own scope (`Marketing/Clerk/Clinic Agent Only`, `Data Analyst Only`) |
| Safety rules | shown on the dashboard; enforced by the existing role code (medical guard, approval gates, no shared memory for clerk/clinic) |

Selecting a role does **not** retrain the language model; it configures what the existing AI Core is given.

## Flow
1. Register (company + admin) -> `/select-role`. Sign in -> `/workspace`; the shell sends anyone without a valid
   selection to `/select-role` (also on direct URLs).
2. The page shows four cards (purpose, capabilities, knowledge domain, main tools); unavailable ones are locked with
   the reason. **Continue** calls `PUT /api/v1/workspace {role_key}`.
3. Later sign-ins reopen the saved workspace. **Switch AI employee** (sidebar and header) returns to the page.
4. If the company deactivates the module (Marketplace) or pauses the role (Employees), the saved choice is kept but
   not used: the person is asked to pick another, with a notice. Re-activating restores it.

## Authorization (server side)
* `PUT /api/v1/workspace` accepts only the four built-in roles, only when the module is active for the caller's
  company and the role is not paused. It is audited (`department = workspace`). Re-selecting the same role is a no-op.
* A workspace is a view, not a permission. Admin pages stay `require_admin`; role APIs stay module-gated:
  clerk, clinic, **datasets/analysis reports** and **campaigns/content/strategy/funnel/performance** (the last two
  groups gained `require_module` in this change). `/agent/execute` still loads tools/persona from the server
  configuration and refuses deactivated or paused roles regardless of what the client sends.
* The frontend hides entries not in `navigation` and shows a "not part of your workspace" panel (with a switch
  button when allowed) for direct URLs. This is convenience; the APIs above are the enforcement.

## Existing accounts (migration `d3e8f05a6b24`)
Every active user whose company has not deactivated the Digital Marketing Manager module gets that workspace with
`source = migration_default` (the only experience EAAWP had before), so nobody is forced into a selection loop. The
shell shows a one-line note offering to choose another. Users of companies that turned that module off, inactive
users and every new user get no row and choose on next sign-in. Downgrade drops only the new table.

## Tests
`tests/test_workspace_selection.py` (32: onboarding, persistence through a real login, switching keeps data,
disabled/paused/unknown roles, direct API access, tenant isolation incl. a forged cross-tenant row, navigation per
role and per admin/employee, AI context equals the server blueprint, medical safety rules),
`tests/test_knowledge_access.py::test_each_workspace_role_retrieves_its_own_scope_and_never_another_roles`,
`tests/security/test_migrations.py::test_user_workspaces_migration_defaults_existing_accounts_and_is_reversible`.
Mutation-checked: module gate, pause gate, admin-only navigation, stale-selection handling, tenant filter.
Real-browser run (system Chrome, scratch DB): registration -> selection -> clerk dashboard -> refresh -> Cabin
answers as the Clerk -> direct URL gate -> switch (gate button and sidebar) -> sign out/in -> module deactivated ->
reselect -> invited employee (no admin entries, `/team` gated) -> 390 px width without overflow.
