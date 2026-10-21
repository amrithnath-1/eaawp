# Security model (Phase 2 + final review)

Source of truth for identity, authorization and abuse protection. Machine-checked
parts are enforced by `tests/security/` and fail CI when they drift.

## Identity
* Every non-public route requires a Bearer JWT (HS256, `SECRET_KEY`). `X-Tenant-ID` is never read.
* Verified on every request: signature, `exp` and `sub` present, not-before, token type
  (`access` vs `refresh`), `iss`/`aud` **when `JWT_ISSUER` / `JWT_AUDIENCE` are set**
  (then they are mandatory), and the user must exist and be `is_active`.
* Tenant and role come from the **database user row**, not from token claims. Demoting or
  deactivating a user takes effect on the next request, without waiting for token expiry.
* Refresh tokens: stored as SHA-256 hashes, single use (rotated), revocable (logout / logout-all),
  signed subject must equal the record's user, user must still be active.
* Startup refuses: empty, short (<32) or placeholder `SECRET_KEY` (anything containing `changeme`, `replace`, `placeholder`, `insecure`, `your-secret`, `generate-a`, ...; `.env.example` ships it empty), non-HMAC `ALGORITHM`, wildcard `CORS_ORIGINS` in production.

## Authorization (RBAC)
Two levels: **Admin** (`Company Admin`, `admin`, `superadmin`, `AI Administrator`) and **member**.
* Admin-only: user/company creation; integrations & data connections (create/update/delete/test/discover/permissions);
  email integration; marketing channels; OAuth connect; role configuration (PUT/PATCH/NL-configure and approvals);
  AI-employee create/status/config and the employee builder; knowledge upload/delete; schedules; monitoring rules;
  data mappings; workflows; admin customisation and provider configuration; all approval decisions.
* Members: day-to-day marketing work (campaigns, content, tasks, strategy, analysis), reading, running the AI employee,
  read-only queries, cancelling a draft, their own notifications.
* `app/core/route_inventory.py::MEMBER_MUTATIONS` lists every state-changing route a member may call, with the reason.
  `tests/security/test_rbac.py` fails if a new state-changing route is neither admin-only nor on that list.
* Full table: `docs/route_auth_inventory.md` (regenerate with `python scripts/route_auth_inventory.py`).

## Intentionally public endpoints (7)
| Endpoint | Why public | Protection |
| --- | --- | --- |
| `GET /health` | Load-balancer probe | Returns status + app version only |
| `POST /api/v1/auth/token`, `/token/form` | Login | Per-IP limit; lockout after N failures per (IP, company, email); uniform 401; constant-time check |
| `POST /api/v1/auth/refresh`, `/logout` | Token exchange / revoke | Per-IP limit; DB-validated single-use token |
| `POST /api/v1/onboarding/company` | Self-service sign-up | Per-IP limit, global daily cap, on/off switch, 72-byte password bound |
| `GET /api/v1/oauth/google/callback` | Browser redirect from Google | Per-IP limit; 256-bit single-use state, atomic consume, 10 min expiry, bound to tenant + initiating active user |

Settings (env): `REGISTRATION_ENABLED`, `REGISTRATION_RATE_LIMIT`, `REGISTRATION_RATE_WINDOW_SECONDS`,
`REGISTRATION_DAILY_CAP`, `LOGIN_RATE_LIMIT`, `LOGIN_MAX_FAILURES`, `LOGIN_FAILURE_WINDOW_SECONDS`,
`REFRESH_RATE_LIMIT`, `OAUTH_CALLBACK_RATE_LIMIT`, `RATE_LIMIT_ENABLED`, `TRUSTED_PROXY_COUNT`.

**Limits of the limiter:** counters are in process memory, so each API worker/replica counts separately and a restart
resets them. Behind a reverse proxy set `TRUSTED_PROXY_COUNT` (otherwise every client looks like the proxy).
For multi-instance production add a shared limiter (proxy or Redis). There is no CAPTCHA or e-mail verification on sign-up.

## OAuth (Google Search Console / Analytics)
Authorize (admin, JWT) → state row `{tenant, initiating user, integration}` → Google → callback consumes the state atomically,
re-checks the initiating user is active in the same tenant, exchanges the code server-side, stores tokens Fernet-encrypted in
`integration_catalog`, audits the connection. Expired access tokens are refreshed and the new token is re-encrypted.
Disconnect revokes the grant at Google (best effort), deletes the integration, its capability grants and its stored credentials.
No token, code or client secret is logged or returned by any API.
Credential encryption key: derived from `ENCRYPTION_KEY` when set, otherwise from `SECRET_KEY`; data written under `SECRET_KEY`
stays readable after you introduce `ENCRYPTION_KEY`. Prefer a dedicated key so rotating the JWT secret does not orphan stored credentials.

## API documentation
`/docs`, `/redoc`, `/openapi.json` (and anything that looks like documentation, including custom routes and mounted
sub-apps) answer 404 whenever `ENVIRONMENT` is `production`/`prod` (case-insensitive), enforced per request by
`app/middleware/docs_guard.py`.

## Data access
`tests/security/test_query_scoping.py` fails on any new query against a tenant-scoped model that lacks a tenant filter unless it is
reviewed and listed with a reason. There are no WebSocket/SSE endpoints. Agent tool context is a `ContextVar` (per task).
The monitoring scheduler is cross-tenant by design and runs each rule under that rule's own tenant.

## Known gaps
See the Phase 2 final report: per-process rate limiting, no CAPTCHA/e-mail verification, no RBAC finer than admin/member,
SQLite-only migration testing, remaining `logger.exception` calls in non-Google providers, stale AGENT.md/README.
