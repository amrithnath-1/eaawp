# Activity history (Phase M)

The audit log is the company's persistent event history: every important action (approvals, workflow runs, module changes, team changes, notification and email settings, exports) writes an immutable row. It is **administrators only** (it records what every person did).

## Audit page (live mode)
- **Search** events (case-insensitive; `%` and `_` are matched literally), **filter** by actor, department, status and a **date range** (whole days, both ends inclusive; UTC).
- **Paging**: 50 rows at a time, "Load more" (server-side, newest first, stable order).
- **Export CSV** of the current filters (up to 5,000 rows). Cells starting with `=`, `+`, `-`, `@` are prefixed with `'` so a spreadsheet shows them as text instead of running them. Every export is itself written to the audit log.
- People appear by name (user ids are resolved within the same company only); a row whose actor is not a user in the company shows the stored value (`AI`, `workflow-runner`, ...).
- Employees see only a short message; the controls are not shown.

## API
`GET /api/v1/audit` with `q, actor, department, status, since, until, limit (1-500), offset (0-100000)`; `GET /api/v1/audit/export` (same filters, CSV). Both admin-only and tenant-scoped; bad dates return 422.

## Verification status
- Backend: `tests/test_audit_history.py` (9) + `tests/test_audit_visibility.py` (4); mutation-checked (wildcard escaping, CSV formula guard, inclusive end date, export filters).
- Real browser on a scratch DB with 148 rows: paging (50 -> 100), department / status / text filters, literal `%` search, empty-filter message, real CSV download (148 rows, expected header), mobile width without horizontal scroll, employee view.
- NOT built: execution traces (no trace feed exists; the page says so), retention/archival policy (Settings shows "Not configured"), tamper-evidence beyond the append-only design, per-user (non-admin) activity view.
