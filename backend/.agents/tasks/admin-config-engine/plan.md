# Implementation Plan — Admin-Assisted Configuration Engine

## Codebase context discovered during exploration

- **Build/test command**: `cd backend && python -m pytest tests/ -v` (pytest, no separate build step needed).
- **Backend**: FastAPI + SQLAlchemy async, SQLite dev / PostgreSQL prod. Sessions via `app.db.session.get_db`.
- **Auth**: `require_admin` in `app/core/auth.py` checks `user.role.lower()` against `{"admin","superadmin","company admin","ai administrator"}`. Use it for admin-only endpoints.
- **Crypto**: `encrypt_password`/`decrypt_password` in `app/integrations/crypto.py` — Fernet, key derived from `settings.secret_key`.
- **Existing settings**: `settings.google_client_id`, `settings.google_client_secret`, `settings.google_redirect_uri` already live in `app/config.py`.
- **AuditLog model**: table `audit_logs`, columns `id`, `tenant_id`, `ai_employee_id` (nullable), `actor`, `event`, `department`, `status`, `created_at`. Use this; do not create a new log table.
- **ORM Base**: `Base` from `app.db.models` (the same `DeclarativeBase` subclass — import it, do not redeclare it).
- **Migration lineage**: latest revision is `t7u1v26w8x14` (`add_refresh_tokens_table`). New migration `down_revision = "t7u1v26w8x14"`.
- **Router registration pattern**: `app.include_router(router)` in `app/main.py`; prefix is set in the router file itself.
- **Alembic scripts dir**: `backend/migrations/versions/`.
- **Frontend pattern**: TypeScript strict, `@/hooks/use-api` for data-fetching hooks, `sonner` for toasts, lucide-react icons, `cn` from `@/lib/utils` for class composition. See `GoogleSearchConsolePanel.tsx` and `NLIntegrationPanel.tsx` as the reference patterns.
- **Test pattern**: Pure pytest, no async fixtures needed for unit tests; mock DB with `AsyncMock`; mock users with `MagicMock` with `.role`, `.tenant_id`, `.id` attributes. See `test_admin_customization.py` and `test_gsc_integration.py`.
- **`nl_integration_service.py`**: `build_conversation_reply` is a sync function. It currently doesn't receive `db`. The plan upgrades it to optionally accept `db: AsyncSession | None = None` and calls an async helper from the service layer using `asyncio.run_coroutine_threadsafe`/`await` only in async callers.

---

## Step-by-step plan

---

- [ ] 1. **Add `ConfigurationField`, `ConfigurationStatus` dataclasses and `configuration_requirements()` ABC method to `provider.py`**

  Add three things to the bottom of `app/integrations/provider.py` (after the existing `IntegrationProvider` class, before the final `__repr__`):
  1. `ConfigurationField` — a frozen dataclass with fields: `key: str`, `display_name: str`, `description: str`, `is_secret: bool`, `required: bool`, `field_type: str` (values: `"identifier"`, `"secret"`, `"url"`, `"text"`), `placeholder: str = ""`, `help_url: str = ""`.
  2. `ConfigurationStatus` — a dataclass with: `provider_type: str`, `state: str` (values: `"NOT_CONFIGURED"`, `"PARTIALLY_CONFIGURED"`, `"CONFIGURED"`, `"VALID"`, `"INVALID"`), `configured_fields: list[str]`, `missing_fields: list[str]`, `oauth_ready: bool`, `redirect_uri: str`, `message: str`.
  3. On `IntegrationProvider` ABC, add a non-abstract method `configuration_requirements(self) -> list[ConfigurationField]` that returns `[]` by default. This is intentionally non-abstract so existing providers don't need to implement it to remain valid.

  Files: `backend/app/integrations/provider.py`
  Verify: `cd backend && python -c "from app.integrations.provider import ConfigurationField, ConfigurationStatus; print('ok')"` — prints `ok` with no import errors.

---

- [ ] 2. **Override `configuration_requirements()` in each provider file**

  For each file listed below, add a `configuration_requirements()` method that returns the named `ConfigurationField` instances. Import `ConfigurationField` from `app.integrations.provider` at the top of each file (it is already imported from the same module for other classes).

  **`google_search_console_provider.py`** and **`google_analytics_provider.py`** (identical fields — both are Google OAuth2 providers):
  ```
  client_id      field_type="identifier"  is_secret=False  required=True  placeholder="*.apps.googleusercontent.com"  help_url="https://console.cloud.google.com/apis/credentials"
  client_secret  field_type="secret"      is_secret=True   required=True  placeholder="GOCSPX-..."
  redirect_uri   field_type="url"         is_secret=False  required=True  placeholder="http://localhost:8000/api/v1/oauth/google/callback"
  ```

  **`github_provider.py`**:
  ```
  personal_access_token  field_type="secret"  is_secret=True  required=True  placeholder="ghp_..."  help_url="https://github.com/settings/tokens"
  ```
  Note: GitHub uses `required_credential_fields = ["github_token"]` for the credential vault; `configuration_requirements()` is for the pre-connection server-level config check — for GitHub, the PAT is the per-connection credential, so this should return `[]` (the admin enters it per-connection in the existing GitHub form). **Decision**: GitHub has no server-level pre-configuration (no OAuth app secret needed server-wide), so `configuration_requirements()` returns `[]` for `github_provider.py`.

  **`facebook_provider.py`**:
  ```
  app_id      field_type="identifier"  is_secret=False  required=True   placeholder="123456789"
  app_secret  field_type="secret"      is_secret=True   required=True   placeholder="..."
  ```
  Note: Facebook's `access_token` is a per-user token from OAuth, not a server-level config field; `app_id` and `app_secret` are the server-level App credentials needed before any OAuth flow.

  **`mcp_provider.py`**:
  ```
  server_url  field_type="url"     is_secret=False  required=True   placeholder="https://your-mcp-server.com"
  api_key     field_type="secret"  is_secret=True   required=False  placeholder="optional-api-key"
  ```
  Note: MCP `server_url` and `api_key` are per-connection credentials (entered each time), not global server config. **Decision**: `mcp_provider.py` also returns `[]` — MCP has no shared server-level credential to pre-configure; the server URL is per-connection.

  **`postgresql_provider.py`** and `mysql_provider.py`: return `[]` — no server-level config.

  In practice the **non-trivial overrides** are only in `google_search_console_provider.py`, `google_analytics_provider.py`, and `facebook_provider.py`.

  Files:
  - `backend/app/integrations/providers/google_search_console_provider.py`
  - `backend/app/integrations/providers/google_analytics_provider.py`
  - `backend/app/integrations/providers/facebook_provider.py`
  - `backend/app/integrations/providers/github_provider.py` (returns `[]`, but add explicit override to document the decision)
  - `backend/app/integrations/providers/mcp_provider.py` (returns `[]`)
  - `backend/app/integrations/providers/postgresql_provider.py` (returns `[]`)
  - `backend/app/integrations/providers/mysql_provider.py` (returns `[]`)

  Verify: `cd backend && python -c "from app.integrations.providers.google_search_console_provider import GoogleSearchConsoleProvider; p=GoogleSearchConsoleProvider(); req=p.configuration_requirements(); assert len(req)==3; assert any(f.is_secret for f in req); print('ok')"` — prints `ok`.

---

- [ ] 3. **Create `ProviderServerConfig` ORM model in a new file**

  Create `backend/app/db/provider_config_models.py`. Import `Base` from `app.db.models` (not a new `DeclarativeBase` — re-use the existing one so Alembic sees the table). Define:

  ```python
  class ProviderServerConfig(Base):
      __tablename__ = "provider_server_configs"
      id: Mapped[str]                 # String(36), PK, default=_uuid
      tenant_id: Mapped[str]          # String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True
      provider_type: Mapped[str]      # String(64), not null
      field_key: Mapped[str]          # String(128), not null
      encrypted_value: Mapped[str]    # Text, not null
      configured_by: Mapped[str]      # String(128), not null
      configured_at: Mapped[datetime] # DateTime(timezone=True), server_default=func.now()
      __table_args__ = (
          UniqueConstraint("tenant_id", "provider_type", "field_key",
                           name="uq_provider_server_config"),
      )
  ```

  Import `_uuid` from `app.db.models` or define it locally (it's just `str(uuid.uuid4())`).

  Files: `backend/app/db/provider_config_models.py`
  Verify: `cd backend && python -c "from app.db.provider_config_models import ProviderServerConfig; print(ProviderServerConfig.__tablename__)"` — prints `provider_server_configs`.

---

- [ ] 4. **Create Alembic migration for `provider_server_configs`**

  Create `backend/migrations/versions/u8v2w37x9y15_add_provider_server_configs.py`.

  Pattern to follow: `t7u1v26w8x14_add_refresh_tokens_table.py` — use `op.create_table()` in `upgrade()` and `op.drop_table()` in `downgrade()`. Key details:
  - `revision = "u8v2w37x9y15"`
  - `down_revision = "t7u1v26w8x14"` (the current HEAD)
  - `branch_labels = None`, `depends_on = None`
  - Columns: `id String(36) PK`, `tenant_id String(36) FK→companies.id CASCADE`, `provider_type String(64) not null`, `field_key String(128) not null`, `encrypted_value Text not null`, `configured_by String(128) not null`, `configured_at DateTime(timezone=True) server_default=sa.func.now()`
  - Unique constraint: `("tenant_id", "provider_type", "field_key")` named `uq_provider_server_config`
  - Index on `tenant_id`

  Also import `ProviderServerConfig` from `app.db.provider_config_models` in `backend/migrations/env.py` (or wherever `target_metadata` is assembled) so Alembic can discover the table. Check `migrations/env.py` — if it imports `Base.metadata` from `app.db.models`, add an import of `app.db.provider_config_models` there so the table is included in `Base.metadata`.

  Files:
  - `backend/migrations/versions/u8v2w37x9y15_add_provider_server_configs.py`
  - `backend/migrations/env.py` (add `import app.db.provider_config_models  # noqa: F401` before `target_metadata`)

  Verify: `cd backend && python -c "from migrations.versions.u8v2w37x9y15_add_provider_server_configs import upgrade, downgrade; print('migration importable')"` — prints `migration importable`.

---

- [ ] 5. **Create `ProviderConfigService` in a new service file**

  Create `backend/app/services/provider_config_service.py`. This file must never log or return secret values. The entire file should be async (FastAPI async session compatible).

  **Imports needed**: `AsyncSession` from sqlalchemy, `select` from sqlalchemy, `AuditLog` from `app.db.models`, `ProviderServerConfig` from `app.db.provider_config_models`, `encrypt_password`/`decrypt_password` from `app.integrations.crypto`, `settings` from `app.config`, `ConfigurationField`, `ConfigurationStatus` from `app.integrations.provider`, `uuid`, `datetime`, `logging`.

  **`async def get_provider_configuration_status(provider_type: str, tenant_id: str, db: AsyncSession) -> ConfigurationStatus`**:
  1. Get the provider's `configuration_requirements()` from `integration_registry.get(provider_type)`. If provider not found or returns `[]`, return `ConfigurationStatus(state="CONFIGURED", configured_fields=[], missing_fields=[], oauth_ready=True, redirect_uri="", message="No server configuration required.")`.
  2. For each `ConfigurationField` in requirements:
     - Check DB: `SELECT encrypted_value FROM provider_server_configs WHERE tenant_id=? AND provider_type=? AND field_key=?` — treat any row found as "configured" (do NOT decrypt, just check presence).
     - For `google_search_console` and `google_analytics`: also check the corresponding `settings.*` env var as a fallback (e.g., `field.key == "client_id"` → check `bool(settings.google_client_id)`, `field.key == "client_secret"` → check `bool(settings.google_client_secret)`, `field.key == "redirect_uri"` → check `bool(settings.google_redirect_uri)`). A field counts as configured if DB row exists OR env var is non-empty.
     - For other providers (facebook): only check DB.
  3. Build `configured_fields` (keys of present fields) and `missing_required_fields` (keys of absent `required=True` fields).
  4. Compute `state`: all required configured → `"CONFIGURED"`, none configured → `"NOT_CONFIGURED"`, some → `"PARTIALLY_CONFIGURED"`.
  5. `oauth_ready`: True when all required fields for `google_*` / `facebook` providers are configured.
  6. `redirect_uri`: for google providers, return `settings.google_redirect_uri` if set, else `"http://localhost:8000/api/v1/oauth/google/callback"`.
  7. Return `ConfigurationStatus`. **Never put decrypted values in any field.**

  **`async def store_provider_field(provider_type: str, field_key: str, value: str, tenant_id: str, configured_by: str, db: AsyncSession) -> None`**:
  1. Validate `value` is non-empty. Raise `ValueError("value cannot be empty")` if blank.
  2. `encrypted = encrypt_password(value)` — value is now discarded.
  3. Upsert: try to find existing row by `(tenant_id, provider_type, field_key)`. If found, update `encrypted_value` and `configured_by` and `configured_at`. If not found, insert new row.
  4. Build `AuditLog(id=str(uuid4()), tenant_id=tenant_id, actor=configured_by, event=f"admin configured {provider_type}.{field_key}", status="ok")` — **`field_key` is safe metadata; value is never logged**.
  5. `db.add(audit_log)`, `await db.flush()`. Do NOT commit (caller's session commits).
  6. Log at DEBUG level only: `"Stored provider config field for %s.%s (tenant %s)", provider_type, field_key, tenant_id`. Never log value.

  **`async def get_decrypted_field(provider_type: str, field_key: str, tenant_id: str, db: AsyncSession) -> str | None`**:
  1. Query `provider_server_configs` for the row.
  2. If not found: for `google_search_console`/`google_analytics` check env var fallback (`settings.google_client_id`, etc.) and return it if present.
  3. If found: return `decrypt_password(row.encrypted_value)`.
  4. Return `None` if nothing found.
  5. This function is for **internal use only** (building OAuth URLs). Never call it from API response paths.

  Files: `backend/app/services/provider_config_service.py`
  Verify: `cd backend && python -c "from app.services.provider_config_service import get_provider_configuration_status, store_provider_field, get_decrypted_field; print('ok')"` — prints `ok`.

---

- [ ] 6. **Create `admin_config` router**

  Create `backend/app/api/routers/admin_config.py`.

  **Router setup**:
  ```python
  router = APIRouter(prefix="/api/v1/admin/provider-config", tags=["admin-config"])
  ```

  **`POST /{provider_type}`** — admin-only:
  - Dependencies: `admin_user: User = Depends(require_admin)`, `db: AsyncSession = Depends(get_db)`.
  - Request body schema (define inline or as a Pydantic model): `class ProviderConfigSubmit(BaseModel): fields: dict[str, str]`.
  - Validate `provider_type` is in `KNOWN_PROVIDERS` (import from `app.schemas.nl_integration`). Return 422 if not.
  - Validate each field value:
    - For `client_id`: must be non-empty string. If the provider is google, optionally warn (but do not hard-reject) if it doesn't match `*.apps.googleusercontent.com` — just ensure it's non-empty and length ≤ 256.
    - For `redirect_uri`: must be a valid URL (use `urllib.parse.urlparse` — scheme must be `http` or `https`, netloc must be non-empty). Return 422 with a safe message if invalid.
    - For all secret fields: must be non-empty (the body value is the plaintext the admin typed; it will be encrypted immediately and discarded).
    - Check which fields are declared `is_secret=True` by calling `provider.configuration_requirements()` — never log or echo those values.
  - For each field in `body.fields`: call `await store_provider_field(provider_type, key, value, admin_user.tenant_id, admin_user.id, db)`. **Do not pass value to any logging call.**
  - Return: `{"status": "ok", "configured_fields": list(body.fields.keys())}` — **never return values**.
  - On `ValueError` from validation: return HTTP 422.
  - 403 comes automatically from `require_admin` for non-admins.

  **`GET /{provider_type}/status`** — any authenticated user:
  - Dependencies: `tenant_id: str = Depends(get_current_tenant_id)`, `db: AsyncSession = Depends(get_db)`.
  - Validate `provider_type` is in `KNOWN_PROVIDERS`. Return 422 if not.
  - Call `await get_provider_configuration_status(provider_type, tenant_id, db)`.
  - Serialize `ConfigurationStatus` to a dict and return it. The serialization must only include: `provider_type`, `state`, `configured_fields` (list of keys), `missing_fields` (list of keys), `oauth_ready`, `redirect_uri`, `message`. **Never include decrypted values.**

  Files: `backend/app/api/routers/admin_config.py`
  Verify: `cd backend && python -c "from app.api.routers.admin_config import router; print(router.prefix)"` — prints `/api/v1/admin/provider-config`.

---

- [ ] 7. **Update `nl_integration_service.py` — add configuration check to CONNECT_INTEGRATION**

  Modify `backend/app/services/nl_integration_service.py`.

  **Change 1 — make `build_conversation_reply` async and accept `db`**:
  - Change signature to `async def build_conversation_reply(intent, tenant_integrations, db: AsyncSession | None = None, tenant_id: str | None = None) -> tuple[str, str, dict]`.
  - Add `from __future__ import annotations` (already present), add `from sqlalchemy.ext.asyncio import AsyncSession` import.

  **Change 2 — configuration check in `CONNECT_INTEGRATION` branch**:
  In the block that handles `intent.intent_type == "CONNECT_INTEGRATION"` and `provider in ("google_search_console", "google_analytics")` (currently returns `REDIRECT_TO_OAUTH` unconditionally), insert before the existing `REDIRECT_TO_OAUTH` return:

  ```python
  if db is not None and tenant_id is not None:
      from app.services.provider_config_service import get_provider_configuration_status
      config_status = await get_provider_configuration_status(provider, tenant_id, db)
      if config_status.state in ("NOT_CONFIGURED", "PARTIALLY_CONFIGURED"):
          missing = config_status.missing_fields
          pname = provider_info["display_name"] if provider_info else provider
          # Build conversational reply listing only missing fields and where to get them
          field_lines = []
          provider_obj = integration_registry.get(provider)
          req_fields = provider_obj.configuration_requirements() if provider_obj else []
          req_map = {f.key: f for f in req_fields}
          for field_key in missing:
              fd = req_map.get(field_key)
              label = fd.display_name if fd else field_key
              secret_note = " (will be stored encrypted, never shown)" if fd and fd.is_secret else ""
              field_lines.append(f"• {label}{secret_note}")
          redirect_uri = config_status.redirect_uri
          reply = (
              f"I can connect {pname}, but Google OAuth is not fully configured yet.\n\n"
              f"I need these settings from Google Cloud Console "
              f"(https://console.cloud.google.com/apis/credentials):\n"
              + "\n".join(field_lines)
              + (f"\n\nIMPORTANT: Register this exact redirect URI in Google Cloud Console:\n{redirect_uri}" if redirect_uri else "")
              + "\n\nWould you like to configure these now? Use the configuration panel or ask me to guide you through each step."
          )
          return (
              reply,
              "CONFIGURATION_REQUIRED",
              {
                  "provider_type": provider,
                  "missing_fields": missing,
                  "redirect_uri": redirect_uri,
                  "config_endpoint": f"/api/v1/admin/provider-config/{provider}",
              },
          )
  ```

  After the check, the existing `REDIRECT_TO_OAUTH` return remains unchanged — it is reached when config is complete.

  **Also add for `facebook` provider** (similar pattern, no `redirect_uri` needed — just missing `app_id`/`app_secret`):
  Add a new block before the final `else:` fallback that handles `provider == "facebook"` with a configuration check:
  ```python
  if provider == "facebook":
      if db is not None and tenant_id is not None:
          from app.services.provider_config_service import get_provider_configuration_status
          config_status = await get_provider_configuration_status(provider, tenant_id, db)
          if config_status.state in ("NOT_CONFIGURED", "PARTIALLY_CONFIGURED"):
              # same pattern as google: build reply with missing fields
              ...
              return (reply, "CONFIGURATION_REQUIRED", {...})
      return (
          "Use the Facebook tab to enter your App credentials and begin the OAuth flow. "
          "EAAWP will save them encrypted and guide you through the authorization.",
          "OPEN_FACEBOOK_FORM",
          {"provider_type": provider},
      )
  ```

  **Security constraint**: The LLM never sees `ConfigurationStatus` — `build_conversation_reply` is called *after* LLM parsing. The `config_status` object contains only booleans and field names; no credential values are placed in the reply.

  Files: `backend/app/services/nl_integration_service.py`
  Verify: `cd backend && python -c "import asyncio; from app.services.nl_integration_service import build_conversation_reply; print('importable')"` — prints `importable`.

---

- [ ] 8. **Add `CONFIGURATION_REQUIRED` to `IntegrationConversationResponse.next_action` Literal**

  In `backend/app/schemas/nl_integration.py`, find the `next_action` Literal in `IntegrationConversationResponse`:

  ```python
  next_action: Literal[
      "NONE",
      "REDIRECT_TO_OAUTH",
      ...
      "UNAVAILABLE",
  ] = "NONE"
  ```

  Add `"CONFIGURATION_REQUIRED"` to the Literal. Also add `"OPEN_FACEBOOK_FORM"` if it is not already present (check the existing Literal — currently it has `OPEN_GITHUB_FORM` and `OPEN_MCP_FORM` but not facebook; add it for consistency with step 7's facebook branch).

  Files: `backend/app/schemas/nl_integration.py`
  Verify: `cd backend && python -c "from app.schemas.nl_integration import IntegrationConversationResponse; r=IntegrationConversationResponse(conversation_id='x', reply='y', next_action='CONFIGURATION_REQUIRED'); print('ok')"` — prints `ok`.

---

- [ ] 9. **Update `nl_integration.py` router — pass `db` and `tenant_id` to `build_conversation_reply`**

  In `backend/app/api/routers/nl_integration.py`, the `chat` endpoint already has `db` and `tenant_id` available as dependencies. Update the call to `build_conversation_reply`:

  ```python
  # Before (sync call):
  reply, next_action, action_data = build_conversation_reply(intent, tenant_integrations)

  # After (async call with db and tenant_id):
  reply, next_action, action_data = await build_conversation_reply(
      intent, tenant_integrations, db=db, tenant_id=tenant_id
  )
  ```

  Since `build_conversation_reply` is now async (step 7), the call site must `await` it.

  No other changes needed in this file.

  Files: `backend/app/api/routers/nl_integration.py`
  Verify: `cd backend && python -c "from app.api.routers.nl_integration import router; print('ok')"` — prints `ok`.

---

- [ ] 10. **Register `admin_config_router` in `main.py`**

  In `backend/app/main.py`, add the import:
  ```python
  from app.api.routers.admin_config import router as admin_config_router
  ```

  And include it alongside the other admin routers (near the bottom of the `app.include_router(...)` block):
  ```python
  app.include_router(admin_config_router)  # Admin config engine — /api/v1/admin/provider-config/*
  ```

  Files: `backend/app/main.py`
  Verify: `cd backend && python -c "from app.main import app; routes=[r.path for r in app.routes]; assert any('/api/v1/admin/provider-config' in p for p in routes); print('ok')"` — prints `ok`.

---

- [ ] 11. **Create `AdminProviderConfigPanel.tsx` frontend component**

  Create `src/components/eaawp/AdminProviderConfigPanel.tsx`.

  **Props interface**:
  ```typescript
  interface AdminProviderConfigPanelProps {
    providerType: string;
    providerDisplayName: string;
    onConfigured?: () => void;
  }
  ```

  **Behavior**:
  - On mount: `GET /api/v1/admin/provider-config/{providerType}/status` to load `ConfigurationStatus`. Show loading spinner while fetching.
  - Render a list of the provider's fields. The fields come from `missing_fields` in the status response — only show fields that are not yet configured.
  - For fields that are already configured (`configured_fields`): show `"<FieldName>: ✓ Configured"` with no input.
  - For missing required fields: render an `<input>` — `type="password"` when the field is a secret (detect by field key suffix: `secret`, `key`, `token`, `password` — or use a `secretFieldKeys` prop), `type="text"` otherwise.
  - The `redirect_uri` (from status response): show as a non-editable read-only text block with a "Copy" button. Label it clearly: "Register this Redirect URI in the provider's developer console."
  - On submit: `POST /api/v1/admin/provider-config/{providerType}` with `{ fields: { [key]: value } }`. Send only the fields the user filled in (exclude already-configured ones and empty inputs).
  - After successful submit: clear all secret input values (set controlled state to `""`), call `onConfigured?.()`, show `toast.success("Configuration saved")`, re-fetch status.
  - Error handling: on 403 show `"You do not have permission to configure this integration. Please ask your Company Admin."` inline (not just a toast). On 422 show the validation error message. On other errors: `toast.error(...)`.
  - **Secret hygiene**: Use React controlled inputs. After submit, explicitly set each secret field's state value to `""` — do not store the secret in any ref or outer state. Do not pass secret values through any logging (`console.log`).
  - Use TypeScript strict types throughout (`ConfigurationStatusResponse` interface, `FieldInputState` type, etc.).
  - Lucide icons: `CheckCircle` for configured fields, `AlertCircle` for missing fields, `Lock` for secret fields, `Copy` for the copy-URI button, `Loader2` for loading.
  - Follow the `cn()` + className pattern from existing panels. No additional CSS files needed.

  **TypeScript interfaces** to define:
  ```typescript
  interface ConfigurationStatusResponse {
    provider_type: string;
    state: "NOT_CONFIGURED" | "PARTIALLY_CONFIGURED" | "CONFIGURED" | "VALID" | "INVALID";
    configured_fields: string[];
    missing_fields: string[];
    oauth_ready: boolean;
    redirect_uri: string;
    message: string;
  }
  ```

  **Note**: This panel is standalone and can be embedded by `NLIntegrationPanel` when `next_action === "CONFIGURATION_REQUIRED"` — the parent panel passes `providerType` and `providerDisplayName` from `action_data`. It can also be linked from `GoogleSearchConsolePanel` and a future `FacebookPanel`.

  Files: `src/components/eaawp/AdminProviderConfigPanel.tsx`
  Verify: `cd kinetic-office-main && npx tsc --noEmit src/components/eaawp/AdminProviderConfigPanel.tsx 2>&1 | head -20` — zero type errors.

---

- [ ] 12. **Wire `AdminProviderConfigPanel` into `NLIntegrationPanel`**

  In `src/components/eaawp/NLIntegrationPanel.tsx`, update the message rendering to handle `next_action === "CONFIGURATION_REQUIRED"`:

  - When the assistant message has `next_action === "CONFIGURATION_REQUIRED"` and `action_data.provider_type` is present, render `<AdminProviderConfigPanel providerType={action_data.provider_type as string} providerDisplayName="..." onConfigured={...} />` inline below the assistant message text.
  - `onConfigured` callback: after successful config, automatically re-send the original user message to the chat (so the conversation continues from where it left off — the agent discovers config is now complete and proceeds to OAuth).

  Files: `src/components/eaawp/NLIntegrationPanel.tsx`
  Verify: The TypeScript compiler accepts the import of `AdminProviderConfigPanel` with no errors — run `npx tsc --noEmit` from the project root.

---

- [ ] 13. **Write tests in `test_admin_config.py`**

  Create `backend/tests/test_admin_config.py` with exactly 13 tests covering the required cases. Use the same patterns as `test_admin_customization.py`: `MagicMock` for users, `AsyncMock` for DB sessions, `patch` to mock service calls. No real DB needed — all tests are unit-level.

  **Helper functions** (define at top of file before tests):
  - `_make_admin_user(tenant_id="test-tenant")` → `MagicMock` with `role="Admin"`, `tenant_id`, `id="user-001"`, `is_active=True`.
  - `_make_non_admin_user(tenant_id="test-tenant")` → same but `role="Employee"`.
  - `_make_mock_db()` → `AsyncMock` session with `.execute` returning a mock result, `.add`, `.flush`.

  **13 tests**:

  1. `test_admin_can_submit_provider_config` — Call `store_provider_field("google_search_console", "client_id", "test-id", "t1", "u1", mock_db)`. Assert it completes without error. Assert mock_db.add was called (AuditLog). Assert mock_db.flush was called.

  2. `test_non_admin_cannot_submit_provider_config` — Call `require_admin(user=non_admin_user)` directly. Assert it raises `HTTPException` with status 403.

  3. `test_missing_fields_detected_for_gsc` — Call `get_provider_configuration_status("google_search_console", "t1", mock_db)` with an empty DB result and `settings.google_client_id = ""`, `settings.google_client_secret = ""`, `settings.google_redirect_uri = ""`. Assert `status.state == "NOT_CONFIGURED"` and `"client_id" in status.missing_fields` and `"client_secret" in status.missing_fields`.

  4. `test_only_missing_fields_returned_when_some_configured` — Mock DB to return a row for `client_id`. With `settings.google_client_secret = ""`. Assert `status.state == "PARTIALLY_CONFIGURED"` and `"client_id" not in status.missing_fields` and `"client_secret" in status.missing_fields`.

  5. `test_secret_values_never_appear_in_configuration_status` — Call `get_provider_configuration_status(...)`. Serialize the result to dict. Assert the string `"GOCSPX-"` does not appear in `str(result_dict)`. Assert the string `"fake-secret"` does not appear.

  6. `test_secret_values_never_appear_in_audit_log` — Call `store_provider_field("google_search_console", "client_secret", "super-secret-value", "t1", "u1", mock_db)`. Capture the `AuditLog` object passed to `mock_db.add`. Assert `"super-secret-value"` does not appear in `audit_log.event`. Assert `"super-secret-value"` does not appear in `str(audit_log.__dict__)`.

  7. `test_config_is_tenant_isolated` — Call `get_provider_configuration_status("google_search_console", "tenant-A", mock_db_A)` and `get_provider_configuration_status("google_search_console", "tenant-B", mock_db_B)` where `mock_db_A` returns a row for `client_id` but `mock_db_B` returns nothing. Assert tenant-A status has `"client_id"` in `configured_fields` while tenant-B does not.

  8. `test_config_encrypted_at_rest` — Call `store_provider_field(...)` with `value="plaintext-secret"`. Capture the `ProviderServerConfig` object passed to `mock_db.add` (via `mock_db.add.call_args`). Assert `config_row.encrypted_value != "plaintext-secret"`. Assert `decrypt_password(config_row.encrypted_value) == "plaintext-secret"`.

  9. `test_invalid_redirect_uri_format_rejected` — Call the admin_config router's POST endpoint handler directly or via `TestClient` with `redirect_uri="not-a-url"`. Assert HTTP 422 is returned.

  10. `test_connect_integration_with_missing_config_returns_configuration_required` — Call `await build_conversation_reply(intent_gsc_connect, [], db=mock_db, tenant_id="t1")` where `mock_db` is configured to return no rows and `settings.google_client_id = ""`. Assert `next_action == "CONFIGURATION_REQUIRED"`. Assert `"client_secret" in action_data["missing_fields"]`.

  11. `test_connect_integration_with_complete_config_returns_redirect_to_oauth` — Same but `settings.google_client_id = "abc.apps.googleusercontent.com"`, `settings.google_client_secret = "secret"`, `settings.google_redirect_uri = "http://localhost:8000/..."`. Assert `next_action == "REDIRECT_TO_OAUTH"`.

  12. `test_nl_chat_for_gsc_produces_redirect_uri_in_action_data` — When config is missing, assert `action_data["redirect_uri"]` is a non-empty string. Assert it starts with `"http"`.

  13. `test_redirect_uri_shown_to_admin_is_actual_callback_url` — `status = await get_provider_configuration_status("google_search_console", "t1", mock_db)`. With `settings.google_redirect_uri = "http://localhost:8000/api/v1/oauth/google/callback"`. Assert `status.redirect_uri == "http://localhost:8000/api/v1/oauth/google/callback"`.

  Files: `backend/tests/test_admin_config.py`
  Verify: `cd backend && python -m pytest tests/test_admin_config.py -v` — all 13 tests pass.

---

## Dependency order summary

```
Step 1  (provider.py dataclasses)
  ↓
Step 2  (provider overrides — depend on ConfigurationField from step 1)
  ↓
Step 3  (ProviderServerConfig model)
  ↓
Step 4  (Alembic migration — depends on model from step 3 + migrations/env.py import)
  ↓
Step 5  (ProviderConfigService — depends on model, crypto, provider dataclasses)
  ↓
Step 6  (admin_config router — depends on service from step 5 + auth from core.auth)
  ↓
Step 7  (nl_integration_service update — depends on service from step 5)
  ↓
Step 8  (schema update — depends on nl_integration_service needing CONFIGURATION_REQUIRED)
  ↓
Step 9  (nl_integration router update — depends on service being async from step 7)
  ↓
Step 10 (main.py registration — depends on router from step 6)
  ↓
Step 11 (frontend panel — depends on API from step 6)
  ↓
Step 12 (NLIntegrationPanel wiring — depends on panel from step 11)
  ↓
Step 13 (tests — depend on all of the above being importable)
```

Steps 3 and 4 are independent of steps 2; steps 11 and 12 are independent of steps 7–10 and can proceed in parallel. Steps 6 and 7 can proceed in parallel once step 5 is done.

---

## Security checklist (verify before committing)

- [ ] `ProviderConfigService.store_provider_field` — confirm no `value` in any `logger.*` call.
- [ ] `admin_config` POST endpoint — confirm response dict has no `fields` values, only keys.
- [ ] `build_conversation_reply` — confirm the reply string contains no decrypted credential values.
- [ ] `AdminProviderConfigPanel` — confirm secret inputs are cleared after submit (`setState("")`).
- [ ] `AuditLog.event` — confirm it contains only `provider_type.field_key`, never the value.
- [ ] `ConfigurationStatus` — confirm it is serialized to only booleans and string keys in all API responses.
- [ ] `get_decrypted_field` — confirm it is called only from internal service code, never from a router response path.
