# EAAWP Integration & MCP Completion Audit — Inspection Report

**Date:** 2025  
**Scope:** Full backend + frontend integration architecture  
**Status:** READ-ONLY inspection — no code was modified

---

## 1. File-by-File Findings

### `backend/app/integrations/provider.py`
**Implements:** Abstract base class `IntegrationProvider` for all external system connectors. Defines `ProviderCapability`, `CapabilityCategory`, `RiskLevel`, `ConnectionTestResult`, `CapabilityResult`, and an SSRF guard (`validate_outbound_host`).  
**Status:** COMPLETE  
**Gaps/TODOs:** None. The ABC is well-documented, stateless-singleton design is correct, and credential-never-stored-on-instance is enforced by design.

---

### `backend/app/integrations/manager.py`
**Implements:** `IntegrationManager` service — CRUD for `integration_catalog`, credential encryption/decryption (Fernet), routing to providers, capability-grant enforcement, entity discovery.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `discover_integration_entities` (line ~165) explicitly notes it does NOT persist entities to `schema_entities`. That means discovered MCP tools and database tables are returned but not saved — callers must persist manually. This is documented but never actually wired up in any router call.
- No audit write for `test_integration` or `create_integration` — only `execute_capability` has a DynamicToolAuditLog path. The existing `DataAccessAudit` is mentioned in the docstring but never called here.

---

### `backend/app/integrations/integration_registry.py`
**Implements:** Application-level singleton registry mapping `provider_type` string → `IntegrationProvider` instance. Auto-registers all 7 built-in providers at module load time.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Provider registration is wrapped in `try/except` with `logger.warning` — a broken provider import silently degrades the registry with no startup-time alert. Consider raising on import failure for critical providers.
- No duplicate-detection for same-type re-registration raises only a warning (by design), but could mask misconfiguration.

---

### `backend/app/integrations/connector.py`
**Implements:** `BaseConnector` ABC with `PostgreSQLConnector` and `MySQLConnector` for test + schema-discovery. Includes async/sync fallback paths, password sanitisation, and a connector registry dict.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- MySQL `test_connection` via `aiomysql` uses `ssl={"ssl_ca": None}` — not a proper SSL configuration. Real SSL would require a cert/CA path.
- `MySQLConnector.discover_schema` uses only sync fallback (no `aiomysql` async path) — minor inconsistency with PostgreSQL.
- No SSRF guard before connecting (unlike `postgresql_provider.py` which calls `validate_outbound_host`). The connector layer is used by the old `DataConnection` system as well and should also block SSRF.

---

### `backend/app/integrations/crypto.py`
**Implements:** Fernet-based symmetric encryption (`encrypt_password` / `decrypt_password`) derived from `SECRET_KEY` via SHA-256. Used by the Integration Manager to encrypt credentials at rest.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Key is derived deterministically from `SECRET_KEY`. If `SECRET_KEY` is the same across environments (dev/staging/prod share a `.env`), credentials encrypted in dev are decryptable in prod. Deployment docs should warn against this.
- No key rotation mechanism. If `SECRET_KEY` changes, all existing encrypted credentials become unreadable with no migration path.

---

### `backend/app/integrations/base.py`
**Implements:** Original (Phase 1) `CompanyDataSource` ABC and `CompanyIntegrationRegistry` — the legacy adapter layer for company databases. Separate from the Phase 2 `IntegrationProvider` system.  
**Status:** STUB — never implemented with real adapters  
**Gaps/TODOs:**
- The docstring says "This file does NOT implement any real adapters — that is a future task." The `CompanyIntegrationRegistry` singleton is defined but never populated.
- This is superseded by `provider.py` + `manager.py`. Can be considered legacy dead code, but nothing has been cleaned up.

---

### `backend/app/integrations/providers/google_search_console_provider.py`
**Implements:** Full GSC OAuth2 provider: `list_sites`, `get_search_analytics`, `get_site_metadata`. Token refresh, date range validation, dimension allow-listing, row limiting.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Token refresh mutates the credentials dict in-place but does NOT persist the new `access_token`/`token_expiry` back to the DB. After refresh, the token in memory is valid for the current request but the DB still holds the expired token — the next request will always trigger a refresh round-trip (wasteful but not broken).
- `_should_refresh_token` has a timezone-aware/naive mismatch branch that could silently always return `True` if `token_expiry` is stored without timezone info.
- `discover_entities` not overridden — returns `[]`. GSC has no schema entities, which is correct.
- Missing URL Inspection capability (`inspect_url` endpoint). Not blocking.

---

### `backend/app/integrations/providers/google_analytics_provider.py`
**Implements:** Full GA4 provider: `list_accounts`, `list_properties`, `run_report`, `get_realtime_report`. Token refresh, metric/dimension allow-listing, row limiting.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Same token persistence gap as GSC: refreshed tokens are not written back to DB.
- `_ensure_fresh_token` uses `datetime.utcnow()` (naive) against `expiry_dt` which may be timezone-aware — potential mismatch causing incorrect refresh decisions.
- `_call_admin_api` uses `analyticsadmin v1beta` and `_call_data_api` uses `analyticsdata v1beta` — both are beta APIs. GA4 Admin API is now `v1` in some regions; should be validated against current API availability.
- `discover_entities` not overridden — returns `[]`. Correct for GA4.

---

### `backend/app/integrations/providers/github_provider.py`
**Implements:** GitHub REST API provider: 6 read capabilities (list repos, get repo, branches, commits, issues, PRs) and 2 write capabilities (create issue, create PR). PAT-based auth. Path traversal prevention via `_safe_name` regex.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Uses synchronous `requests` library in `asyncio.get_running_loop().run_in_executor()` — correct pattern but adds thread-pool pressure under load.
- `create_issue` and `create_pull_request` are HIGH risk and flow through the CapabilityGrant check in the manager, but there is no explicit approval workflow integration check within the provider itself — it relies entirely on `execute_capability` in `manager.py` having verified the grant. This is architecturally correct but brittle if the provider is ever called directly (e.g., in tests).
- No token scoping validation — the provider cannot verify that the supplied PAT has the required scopes before attempting an operation.

---

### `backend/app/integrations/providers/facebook_provider.py`
**Implements:** Meta/Facebook Graph API provider: `list_pages`, `get_page_insights`, `list_ad_accounts`, `get_campaign_metrics`, `get_ad_metrics`. Read-only. Access token auth.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Uses Facebook Graph API `v18.0` hardcoded — this version was deprecated in 2024. Should be updated to `v20.0` or later and ideally made configurable.
- Page access tokens differ from user access tokens. `_list_pages` calls `/me/accounts` which returns page access tokens in the response — these are NOT filtered/scrubbed from the response data. Sensitive token leakage risk if the raw `data` dict is ever logged.
- No token expiration handling. Facebook user access tokens expire in ~60 days; there is no refresh flow or expiry check.
- `get_ad_metrics` allows `ad_name` and `ad_id` fields beyond `_ALLOWED_CAMPAIGN_FIELDS`, but the validation set is `_ALLOWED_CAMPAIGN_FIELDS | {"ad_name", "ad_id"}` — this is correct but the docstring only mentions campaign fields.

---

### `backend/app/integrations/providers/mcp_provider.py`
**Implements:** MCP (Model Context Protocol) meta-provider with full tool discovery, prompt-injection rejection, SSRF validation, risk auto-classification, size/timeout bounds, and `tools/call` execution.  
**Status:** COMPLETE — most security-hardened provider in the codebase  
**Gaps/TODOs:**
- MCP protocol transport: uses HTTP POST to `<server_url>/mcp` with JSON-RPC 2.0. The MCP spec supports both HTTP (Streamable HTTP) and SSE transports — SSE transport is not implemented. Some MCP servers require SSE.
- `_validate_mcp_url` resolves DNS at validation time for SSRF checking but not at call time — DNS rebinding attacks could redirect to an internal host after the initial check passes. `_mcp_request` should also call `validate_outbound_host` on the resolved IP.
- `call_tool` capability has `risk_level=MEDIUM` at the meta level but individual tools can be `HIGH`. The CapabilityGrant system only knows about `call_tool` — there is no per-discovered-tool grant. An admin must grant `call_tool` to a role, and then any tool on that server can be called by that role regardless of per-tool risk. This is a governance gap for MCP servers with mixed-risk tools.
- The `discover_entities` method returns tool descriptors but they are never auto-persisted to any DB table.

---

### `backend/app/integrations/providers/postgresql_provider.py`
**Implements:** PostgreSQL Integration Framework provider wrapping the existing `PostgreSQLConnector`. Exposes `discover_schema` and `query_entity`. Includes SSRF guard via `validate_outbound_host`.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `query_entity` returns an error message directing the caller to use the Integration Manager — it cannot be called standalone. This is correct by design but confusing in tests.
- `discover_entities` wraps `_execute_discover_schema` and returns `[]` on error with no logged warning. Silent failures in entity discovery.

---

### `backend/app/integrations/providers/mysql_provider.py`
**Implements:** MySQL/MariaDB provider, structurally identical to PostgreSQL provider.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Same `query_entity` stub issue as PostgreSQL.
- No SSRF guard (`validate_outbound_host`) called in `test_connection` — unlike the PostgreSQL provider which calls it. **Security gap.**

---

### `backend/app/api/routers/integration_manager.py`
**Implements:** Full REST router for the Integration Framework: providers catalogue, status, CRUD for integrations, test, discover, capability grants CRUD, capability execution, and dynamic tool discovery (`/tools`).  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `list_providers` and `framework_status` endpoints do NOT require authentication. This exposes the provider catalogue (including capability descriptions) to unauthenticated callers. Low risk but inconsistent with rest of API.
- `execute_capability` does not require `require_admin` — any authenticated user can call it. Grant check is done inside the manager, but role_key comes from the request body (`body.role_key`) which the client controls. A client could supply a `role_key` they don't belong to. Should be derived from the authenticated user's role.
- No rate limiting on the `/execute` endpoint.

---

### `backend/app/api/routers/oauth_router.py`
**Implements:** Full Google OAuth2 web server flow for both GSC and GA. State token generation, DB storage, CSRF validation, token exchange, credential encryption, and frontend redirect.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `google_authorize` (line ~144) calls `db.commit()` inside the route — but the outer `get_db` dependency uses a context manager that commits on exit. Double-commit risk. Should use `await db.flush()` to be consistent with the rest of the codebase.
- No cleanup of expired/unused `OAuthState` records. The table will grow indefinitely. Should add a periodic cleanup task.
- `get_optional_tenant_id` is used (not `get_current_tenant_id`) — unauthenticated callers can initiate an OAuth flow for `"default-tenant"`. This may be intentional for the demo but is insecure in production.
- OAuth callback reconstructs the Flow with hardcoded `client_config` — if credentials rotate during an in-flight OAuth flow, the exchange will fail. Fine for current usage.
- After OAuth callback success, integration status is still `"not_tested"` until a manual test is called. Should auto-call `test_integration` on successful callback so the status transitions to `"connected"` immediately.

---

### `backend/app/api/routers/nl_integration.py`
**Implements:** NL integration chat (`/chat`) and parse (`/parse`) endpoints. LLM intent classification, current integration state context, and next_action hint routing.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- No conversation history persistence — every `/chat` call is stateless. The `conversation_id` is generated but not used to retrieve prior turns. Multi-turn flows start fresh each time.
- The `/parse` endpoint is unauthenticated beyond tenant derivation — any authenticated tenant can call it freely. No rate limiting.
- `CONNECT_INTEGRATION` for `facebook` falls through to the `else` branch which says "setup flow is not available yet" — but the Facebook provider IS registered. The NL service needs a `REDIRECT_TO_OAUTH` case for Facebook (it uses a different OAuth flow than Google).

---

### `backend/app/api/routers/execution.py`
**Implements:** Main agent execution router. Supports simple engine mode and planning mode. Server-side blueprint override (prevents privilege escalation), RAG integration, dynamic tool injection via ContextVars, memory service integration.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- Dynamic tool adapter in `dynamic_tool.py` has a **critical async bug**: `_adapter_fn` calls `loop.run_until_complete(coro)` but inside an already-running event loop this raises `RuntimeError`. The fallback is `return "[PENDING] ... result will be returned by the engine"` — meaning dynamic tools silently fail in the actual agent execution loop. The correct pattern is `await` or using `asyncio.ensure_future`. This is a **P0 bug**.
- `_blueprint_role_key` mapping is hardcoded for 7 roles — any new role not in the dict defaults to `DIGITAL_MARKETING_MANAGER`.

---

### `backend/app/services/nl_integration_service.py`
**Implements:** LLM-based intent parsing (`parse_integration_intent`) and a deterministic reply builder (`build_conversation_reply`). Uses the configured LLM gateway, not hardcoded model.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `UNKNOWN` providers in the `CONNECT_INTEGRATION` branch fall to "setup flow not available" for Facebook specifically. Should be extended to cover Facebook OAuth.
- `build_conversation_reply` is purely deterministic (no LLM call) — this means responses for edge cases like `REVOKE_CAPABILITY`, `TEST_CONNECTION`, `DISCONNECT_INTEGRATION` all fall to the generic fallback.

---

### `backend/app/services/planner.py` (first 100 lines)
**Implements:** Multi-step planning service with LLM plan generation, step execution ordering, action governance routing, plan pause/resume.  
**Status:** PARTIAL (first 100 lines read — full file not inspected)  
**Gaps/TODOs:** Based on visible code, the planner system prompt is well-structured. Full assessment requires reading the rest of the file.

---

### `backend/app/tools/dynamic_tool.py`
**Implements:** Phase 3 dynamic capability→tool bridge. `DynamicToolDefinition`, `make_tool_key`, `validate_tool_arguments`, `build_dynamic_tool_adapter`, `get_available_tools`, and audit writing.  
**Status:** PARTIAL — critical async bug  
**Gaps/TODOs:**
- **P0 Bug:** `_adapter_fn` (the LangChain tool body) calls `loop.run_until_complete(coro)` when `loop.is_running()` is True — returns `[PENDING]` string instead of actual result. Dynamic tools will never return real data in production. The fix is to make the adapter async or use a thread with `asyncio.run_coroutine_threadsafe`.
- The adapter is synchronous by design (LangChain `@tool` without `coroutine=True`) but executes async code — this fundamental mismatch is the root of the P0 bug.
- `_write_dynamic_tool_audit` has the same `loop.is_running()` path issue — audit writes use `loop.create_task()` which is correct but the task may not complete before the request ends.

---

### `backend/app/tools/registry.py` (first 100 lines)
**Implements:** `MASTER_TOOL_REGISTRY`, `ContextVar` definitions for DB session, tenant, role, allowed tools, guarded tools, and dynamic tools. `set_tool_context` / `clear_tool_context` lifecycle.  
**Status:** COMPLETE (visible portion)  
**Gaps/TODOs:** The ContextVar approach is correct for per-request isolation. The `clear_tool_context` call in the `finally` block of `execution.py` ensures cleanup.

---

### `backend/app/db/integration_models.py`
**Implements:** Three ORM models: `Integration` (integration_catalog), `CapabilityGrant` (capability_grants), `DynamicToolAuditLog` (dynamic_tool_audit_logs). Includes all required fields, cascade deletes, unique constraints, and indexes.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `Integration.status` is a plain `String(20)` with no DB-level constraint — invalid statuses can be written. A `CheckConstraint` would enforce the lifecycle.
- `DynamicToolAuditLog.integration_id` explicitly has no FK cascade (`# No FK cascade — audit records should survive integration deletion`) which is correct for audit immutability.
- No migration scripts inspected — it is unknown whether these tables exist in the actual DB.

---

### `backend/app/db/oauth_models.py`
**Implements:** `OAuthState` ORM model for CSRF state token storage. Includes `state_token` (unique, indexed), `tenant_id` (FK cascade), `integration_id` (FK cascade), `provider_type`, `expires_at`, and `used` flag.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- No automated cleanup of expired/used records. The table accumulates stale rows.
- The `used` column defaults to `False` with `server_default="0"` — should be `server_default=false()` for PostgreSQL boolean compatibility.

---

### `src/components/eaawp/NLIntegrationPanel.tsx`
**Implements:** Chat-based NL integration setup UI. Quick prompts, message rendering, OAuth redirect handling for GSC and GA, GitHub/MCP form opening via `onOpenTab`.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- No error boundary — a failed `chatMutation` appends an error message to the chat but does not recover gracefully from network failures.
- `handleAction(REDIRECT_TO_OAUTH)` for unknown providers just shows a toast — the user gets no actionable next step for Facebook.
- No loading skeleton or optimistic UI for the quick prompts.
- `onOpenTab` only handles `"github"` and `"mcp"` — Facebook and database providers have no tab routing.

---

### `src/hooks/use-api.ts` — Integration-related hooks
**Implements:** `useNLIntegrationChat`, `useNLIntegrationParse`, `intMgrFetch`, `useCreateIntegration`, `useTestIntegration`, `useGscAuthorize`, `useGaAuthorize`, `useCapabilityGrants`, `useCreateCapabilityGrant`, `useBuildEmployee`, `useEmployeeBlueprints`, `useApproveBlueprint`.  
**Status:** COMPLETE  
**Gaps/TODOs:**
- `intMgrFetch` ignores the `_tenantId` parameter — the comment says "kept for signature compatibility; apiClient reads from localStorage". This means tenant isolation at the API call level depends on localStorage being correctly set, not a verified JWT. If localStorage is manipulated, wrong tenant data is fetched.
- `useGscAuthorize` and `useGaAuthorize` use `useMutation` with a GET request — semantically wrong (mutations should be POST/PUT/DELETE). Should be `useQuery` or use POST to initiate the flow.
- No `useFacebookAuthorize` hook exists — Facebook OAuth is not wired in the frontend at all.
- `useIntegrations` does not fall back to mock data (unlike most other hooks) — if the backend is down it fails silently.

---

## 2. Implementation Matrix

| # | Capability | Status | Notes |
|---|-----------|--------|-------|
| 1 | IntegrationManager (CRUD, list, test, disconnect) | **COMPLETE** | Full CRUD, test, disconnect all implemented |
| 2 | IntegrationRegistry (provider catalogue) | **COMPLETE** | 7 providers auto-registered at startup |
| 3 | CredentialVault (encryption at rest) | **COMPLETE** | Fernet AES-128 via crypto.py |
| 4 | OAuth flow (GSC + GA — same credentials) | **COMPLETE** | Both providers share Google OAuth client |
| 5 | OAuth callback handler | **COMPLETE** | CSRF state, one-time-use, tenant-bound |
| 6 | Token refresh | **PARTIAL** | Refresh works but new token not persisted to DB |
| 7 | CapabilityGrant system | **COMPLETE** | DB model, manager CRUD, enforcement |
| 8 | DynamicToolRegistry (per-request tool loading) | **COMPLETE** | get_available_tools queries DB per request |
| 9 | DynamicToolExecution | **PARTIAL — P0 BUG** | Async/await mismatch: tools return [PENDING] |
| 10 | NL Integration Discovery ("connect GSC" → intent) | **COMPLETE** | LLM intent parse + deterministic reply builder |
| 11 | GSC provider (capabilities, execution, tenant isolation) | **COMPLETE** | 3 capabilities, token refresh, bounds |
| 12 | GA provider (capabilities, execution, tenant isolation) | **COMPLETE** | 4 capabilities, token refresh, bounds |
| 13 | GitHub provider (capabilities, READ/WRITE classification) | **COMPLETE** | 6 read + 2 write, HIGH-risk classification |
| 14 | Facebook/Meta provider | **PARTIAL** | Provider exists, no OAuth frontend flow |
| 15 | MCP provider (discovery, execution, security) | **COMPLETE** | Injection check, SSRF, timeout, size bounds |
| 16 | PostgreSQL provider | **COMPLETE** | discover_schema + query_entity stub |
| 17 | MySQL provider | **PARTIAL** | Missing SSRF guard in test_connection |
| 18 | Screaming Frog | **MISSING** | No evidence anywhere in codebase |
| 19 | Connection state machine | **PARTIAL** | Status field exists; lifecycle enforced in code but no DB constraint |
| 20 | Approval/governance for WRITE/DESTRUCTIVE tools | **PARTIAL** | HIGH risk blocks at tool layer; existing approval service exists but MCP per-tool grants not granular |
| 21 | Tenant isolation on all DB queries | **COMPLETE** | All manager queries filter by tenant_id |
| 22 | Secret redaction from logs/LLM/responses | **COMPLETE** | _sanitise_error in all providers; _FORBIDDEN_PARAM_FIELDS in dynamic tools |
| 23 | Frontend Integration Manager UI | **COMPLETE** | NLIntegrationPanel + hooks; missing Facebook OAuth tab |
| 24 | AI Employee Builder | **COMPLETE** | useBuildEmployee, useApproveBlueprint in hooks; /api/v1/employees/build endpoint |
| 25 | Workflow Engine | **PARTIAL** | Planner + execution router exist; full workflow engine inspection not done |

---

## 3. Gap Analysis

### P0 — Security/Correctness Blockers

**P0-1: Dynamic tool execution always returns [PENDING]**  
File: `backend/app/tools/dynamic_tool.py`, function `_adapter_fn` (~line 200)  
Root cause: `loop.run_until_complete(coro)` inside a running event loop raises `RuntimeError`; the except branch returns a `[PENDING]` string. All dynamic integration tools (GSC analytics, GA reports, GitHub queries, etc.) return `[PENDING]` instead of real data when called from the agent engine.  
Fix: Make `_adapter_fn` async (LangChain supports async tools with `coroutine=True`), or use `asyncio.run_coroutine_threadsafe(coro, loop).result()` in an executor thread.

**P0-2: execute_capability role_key comes from client request body**  
File: `backend/app/api/routers/integration_manager.py`, endpoint `execute_capability` (~line 195)  
Root cause: `body.role_key` is supplied by the API caller without being validated against the authenticated user's actual roles. A caller can supply `role_key="ADMIN"` to attempt grant bypasses.  
Fix: Derive `role_key` from the authenticated JWT claims, not the request body.

**P0-3: MySQL provider missing SSRF guard**  
File: `backend/app/integrations/providers/mysql_provider.py`, `test_connection` method  
Root cause: `validate_outbound_host` is called in `postgresql_provider.py` but omitted in `mysql_provider.py`. A customer-supplied MySQL host could be an internal SSRF target.  
Fix: Add `validate_outbound_host(str(credentials["host"]))` before creating the connector.

---

### P1 — Required for End-to-End Integration

**P1-1: Refreshed OAuth tokens not persisted to DB**  
Files: `google_search_console_provider.py` `_refresh_access_token()`, `google_analytics_provider.py` `_refresh_token()`  
Effect: Every request refreshes the token in memory but the DB always stores the original expired token. On restart, the token is expired and a silent refresh occurs on every single request — will hit Google's token refresh rate limit.  
Fix: After token refresh, call `update_integration()` on the Integration record to persist the new `access_token` and `token_expiry`.

**P1-2: OAuth callback does not auto-test the connection**  
File: `backend/app/api/routers/oauth_router.py`, `google_callback()` (~line 190)  
Effect: After OAuth succeeds, integration status remains `"not_tested"` until an admin manually calls the test endpoint. The frontend sees a `not_tested` status and the NL chat would say "not connected".  
Fix: Call `test_integration(integration_id, tenant_id, db)` inside the callback after credential storage.

**P1-3: Facebook OAuth has no frontend flow**  
Files: `src/hooks/use-api.ts` (no `useFacebookAuthorize`), `src/components/eaawp/NLIntegrationPanel.tsx` (`handleAction` has no Facebook case)  
Effect: Users cannot connect Facebook despite the provider being registered and functional. The NL chat returns "setup flow not available".  
Fix: Add `POST /api/v1/oauth/facebook/authorize` backend endpoint + `useFacebookAuthorize` hook + frontend `handleAction` case.

**P1-4: MCP per-tool governance gap**  
File: `backend/app/integrations/providers/mcp_provider.py`  
Effect: Granting `call_tool` to a role gives access to ALL tools on the MCP server regardless of individual tool risk level. A HIGH-risk `delete_everything` tool is accessible if `call_tool` is granted, even if only read tools were intended.  
Fix: Either (a) require a separate CapabilityGrant per discovered MCP tool name, or (b) enforce that HIGH-risk MCP tools block at the provider level (currently they only classify, not block).

**P1-5: NL Integration service has no Facebook OAuth routing**  
File: `backend/app/services/nl_integration_service.py`, `build_conversation_reply()` CONNECT_INTEGRATION branch  
Effect: "Connect Facebook" returns "setup flow not available" instead of routing to an OAuth flow.  
Fix: Add a `REDIRECT_TO_OAUTH` case for `facebook` once the backend OAuth endpoint exists.

---

### P2 — Important UX / Robustness

**P2-1: NL chat has no conversation history**  
File: `backend/app/api/routers/nl_integration.py`  
Effect: Multi-turn flows ("connect GSC" → "which property?" → "example.com") reset every turn.  
Fix: Persist conversation turns keyed by `conversation_id` (Redis or DB table).

**P2-2: OAuth state records never cleaned up**  
File: `backend/app/db/oauth_models.py`  
Fix: Add a background task to `DELETE FROM oauth_states WHERE expires_at < NOW() OR used = TRUE`.

**P2-3: Token refresh uses naive/aware datetime mismatch**  
Files: `google_search_console_provider.py` `_should_refresh_token`, `google_analytics_provider.py` `_ensure_fresh_token`  
Effect: If `token_expiry` is stored without timezone info, the comparison `datetime.now(timezone.utc) >= expiry_dt` may raise or always return True.  
Fix: Normalise all datetime comparisons to UTC-aware.

**P2-4: Facebook Graph API version is deprecated (v18.0)**  
File: `backend/app/integrations/providers/facebook_provider.py` line ~30  
Fix: Update `_GRAPH_BASE` to `v20.0` or latest stable.

**P2-5: `list_providers` and `framework_status` are unauthenticated**  
File: `backend/app/api/routers/integration_manager.py` lines ~60-80  
Fix: Add `Depends(get_current_tenant_id)` to avoid exposing provider metadata to unauthenticated callers.

**P2-6: No integration-related audit trail beyond DynamicToolAuditLog**  
Effect: `create_integration`, `test_integration`, `update_integration`, OAuth flows — none write to any audit log. Only tool execution is audited.  
Fix: Emit audit events for OAuth completion, credential rotation, and grant changes.

---

### P3 — Nice to Have

**P3-1: Screaming Frog integration is entirely absent**  
Effect: The task brief mentions Screaming Frog; no provider, no connector, no mention in the codebase. Must be built from scratch if required.

**P3-2: GSC URL Inspection capability missing**  
The brief mentions URL inspection; `google_search_console_provider.py` does not include it.

**P3-3: Connection state machine has no DB-level constraint**  
`Integration.status` is a free String — invalid states can be written.

**P3-4: MCP SSE transport not supported**  
MCP servers requiring Server-Sent Events transport cannot be connected.

**P3-5: Facebook page access tokens in API response not scrubbed**  
`_list_pages` returns raw Graph API data which may include page `access_token` fields.

**P3-6: Crypto module has no key rotation path**  
Changing `SECRET_KEY` makes all stored credentials unreadable.

---

## 4. Priority Summary

| ID | Priority | Description | File | Action |
|----|----------|-------------|------|--------|
| P0-1 | **P0** | Dynamic tools return [PENDING] — execution broken | dynamic_tool.py | Fix async adapter |
| P0-2 | **P0** | role_key comes from client body — privilege escalation | integration_manager.py router | Derive from JWT |
| P0-3 | **P0** | MySQL missing SSRF guard | mysql_provider.py | Add validate_outbound_host |
| P1-1 | P1 | Refreshed tokens not persisted | gsc+ga providers | Persist after refresh |
| P1-2 | P1 | OAuth callback does not auto-test | oauth_router.py | Call test_integration |
| P1-3 | P1 | Facebook OAuth has no frontend flow | hooks + frontend | Add OAuth endpoint + hook |
| P1-4 | P1 | MCP per-tool governance gap | mcp_provider.py | Per-tool grants |
| P1-5 | P1 | NL service doesn't route Facebook OAuth | nl_integration_service.py | Add REDIRECT_TO_OAUTH case |
| P2-1 | P2 | NL chat has no conversation history | nl_integration router | Add turn persistence |
| P2-2 | P2 | OAuth state records never cleaned up | oauth_models.py | Background cleanup task |
| P2-3 | P2 | Datetime naive/aware mismatch in token refresh | gsc+ga providers | Normalise to UTC-aware |
| P2-4 | P2 | Facebook Graph API v18.0 deprecated | facebook_provider.py | Upgrade to v20.0+ |
| P2-5 | P2 | Provider catalogue endpoints unauthenticated | integration_manager.py | Add auth dependency |
| P2-6 | P2 | No audit trail for OAuth / credential ops | oauth_router + manager | Emit audit events |
| P3-1 | P3 | Screaming Frog entirely absent | N/A | New provider if required |
| P3-2 | P3 | GSC URL Inspection missing | gsc_provider.py | Add capability |
| P3-3 | P3 | Status field has no DB constraint | integration_models.py | Add CheckConstraint |
| P3-4 | P3 | MCP SSE transport not supported | mcp_provider.py | Add SSE transport |
| P3-5 | P3 | Facebook page tokens not scrubbed | facebook_provider.py | Filter token fields |
| P3-6 | P3 | No crypto key rotation | crypto.py | Add migration utility |

---

*Report generated by automated codebase inspection. No code was modified.*
