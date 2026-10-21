# Company database connectivity (Phase K, part 1)

Admins connect a PostgreSQL/MySQL database at **Connections** (`/connections`; also the SMTP email sender lives there), test it, discover its
tables, choose which tables the AI may read, and now which COLUMNS. The AI never sees raw SQL access: it sends a structured query
(entity, fields, filters, sort, limit) and the backend builds a parameterised, read-only SELECT.

## Protections (all enforced in the backend)
* **Table allow-list**: nothing is readable until an admin allows that table (default: denied).
* **Column blocking (new)**: columns whose names look sensitive (ssn, password, token, card, iban, salary, dob, medical ...) are blocked
  by default at discovery. Admins can block/unblock any column (`PATCH /api/v1/integrations/entities/{id}/columns`, audited). A blocked
  column cannot be selected, filtered on or sorted by (those would leak values by inference); "all columns" leaves it out; a semantic
  mapping pointing at it is refused. Re-discovery keeps admin choices and only auto-blocks NEW sensitive-looking columns.
* **Read-only**: PostgreSQL sessions are opened with `default_transaction_read_only=on` (proved against a role that CAN write); MySQL
  uses `SET SESSION TRANSACTION READ ONLY`. Prefer a SELECT-only database user anyway.
* **Outbound-host guard (new)**: link-local/cloud-metadata/multicast/reserved hosts are always refused; in `ENVIRONMENT=production`
  loopback/private hosts are refused too unless `ALLOW_PRIVATE_DB_HOSTS=true`. Applied on create, edit, test, discover and every query.
  Known limit: name resolution happens again in the driver (DNS rebinding only partly mitigated).
* Changing host/port/database/user resets the connection to "not tested"; queries need a connected connection.
* Credentials are Fernet-encrypted at rest, never returned, never sent to the LLM, never in audit rows.
* Every query attempt (including refused ones) is in the data-access audit: fields, filter count, row count, outcome; no values.

## Bugs fixed on the way
* Refused/failed queries were never audited (the audit row was rolled back with the 403).
* Editing a data connection returned a 500 (MissingGreenlet on `updated_at`).
* The admin screens for databases/email were unreachable for logged-in users in real mode (only on `/company`, which redirects away). New `/connections` page.
* Parameter binding is now whole-token (`:p1` vs `:p10`; latent - filters are capped at 10).

## Verification
* Offline: `tests/test_data_connectivity.py` (22 tests, driver faked, 12 mutation checks caught).
* **Live PostgreSQL 16** (`tests/test_data_connectivity_live_pg.py`, 8 tests, skipped unless `EAAWP_TEST_PG_*` is set): real connect, discover, rows with
  filter/sort/limit, blocked `ssn`, injection-as-value, read-only enforcement, wrong password, audit. Plus a real-browser run through the UI.
* NOT verified: MySQL (no server here), SSL/TLS to a managed provider, very large schemas, pooled/slow databases.

## Not in this part
* MCP: a provider exists in the integration framework (`app/integrations/providers/mcp_provider.py`, SSRF-guarded) and is mock-tested only; not wired
  into a user-facing flow and not verified against a real MCP server. Knowledge-base upload/search exists from earlier phases and was not re-verified here.
* Migration `f9a3b48c0d56` (additive; one column).
