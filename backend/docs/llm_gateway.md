# EAAWP LLM Gateway — Technical Documentation

**Phase 1 — LLM Gateway / Model Abstraction**  
**Status:** IMPLEMENTED

---

## Why the LLM Gateway Exists

Before Phase 1, every component that needed an LLM created its own `ChatOpenAI` instance directly, hardcoding the model name at each call site:

```python
# OLD — scattered across 4 files, 5 locations
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
```

Problems this caused:
- No central control over which models could be used
- No validation of model names before API calls were made
- `OPENAI_API_KEY` was implicitly read from the environment with no application-level check
- Adding a second LLM provider (Anthropic, Google) would require changing every call site
- Role-configured `llm_model` was ignored by 4 out of 5 call sites

The LLM Gateway is the single controlled entry point that fixes all of these.

---

## Architecture

```
Application components (engine, planner, content, config_interpreter)
        ↓
   LLMGateway             app/llm/gateway.py
        ↓
   Provider Factory        app/llm/factory.py
        ↓
   OpenAIProvider          app/llm/providers/openai_provider.py
        ↓
   ChatOpenAI (LangChain)
        ↓
   OpenAI API
```

### Module layout

```
backend/app/llm/
├── __init__.py              Public surface: LLMConfig, LLMProvider, get_llm_gateway, exceptions
├── config.py                LLMConfig, LLMProvider, ALLOWED_MODELS, llm_config_from_settings
├── exceptions.py            LLMGatewayError, LLMConfigurationError, LLMUnsupportedModelError, LLMProviderError
├── factory.py               get_provider() — maps LLMProvider → BaseLLMProvider
├── gateway.py               LLMGateway, get_llm_gateway() singleton, LLMHealthStatus
└── providers/
    ├── __init__.py
    ├── base.py              BaseLLMProvider ABC
    └── openai_provider.py   OpenAIProvider (only real provider in Phase 1)
```

---

## How Model Selection Works

### Application-controlled allowlist (`ALLOWED_MODELS`)

```python
# app/llm/config.py
ALLOWED_MODELS: dict[str, frozenset[str]] = {
    LLMProvider.OPENAI: frozenset({
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    }),
}
```

This list is **server-side only**. No frontend payload, tenant value, or user-controlled string can inject a model outside this list. Any attempt raises `LLMUnsupportedModelError` before any network call is made.

### Precedence order

1. Explicit `model=` argument to `gateway.get_chat_model()` — highest priority
2. `role_llm_model` from `AgentBlueprint.llm_model` (set by role configuration) via `get_chat_model_for_role()`
3. `settings.llm_default_model` (environment variable `LLM_DEFAULT_MODEL`, defaults to `"gpt-4o-mini"`)

All three paths go through `ALLOWED_MODELS` validation.

### Role-level model selection

`RoleConfiguration.llm_model` (stored in the database) is the existing mechanism for per-role model configuration. It is validated at write time by `RoleConfigUpdate.validate_llm_model`, and validated again at read time when the gateway calls `get_chat_model_for_role()`. The double validation provides defence-in-depth.

To wire the role's stored model into the engine, set `AgentBlueprint.llm_model` when building the blueprint from the role configuration.

---

## How OpenAI Is Configured

### Required environment variable

```bash
OPENAI_API_KEY="sk-..."
```

Set in `backend/.env` (never committed). Read by `app.config.Settings` via Pydantic BaseSettings.

### Optional environment variable

```bash
LLM_DEFAULT_MODEL="gpt-4o-mini"   # default — can be overridden here
```

### Credential flow

```
OPENAI_API_KEY (environment)
  → Settings.openai_api_key
    → llm_config_from_settings()
      → LLMConfig._api_key (private attribute, never serialised)
        → OpenAIProvider.get_chat_model(config)
          → ChatOpenAI(api_key=config.api_key)
            → OpenAI API
```

The key is only ever passed as a constructor argument to `ChatOpenAI`. It never:
- appears in `LLMConfig.__repr__()` or `__str__()`
- appears in `LLMConfig.model_dump()`
- appears in `LLMConfig.safe_dict()`
- appears in `LLMHealthStatus`
- appears in any API response
- appears in logs

---

## Where Credentials Live

| Location | What lives there |
|---|---|
| `backend/.env` | `OPENAI_API_KEY` (never committed) |
| `app.config.Settings` | `settings.openai_api_key` — read once at startup |
| `LLMConfig._api_key` | Private attribute, excluded from all serialisation |
| `ChatOpenAI` constructor | Passed as argument, not stored in application state |

**Not stored in:** database, frontend state, logs, audit records, LLM prompts, tool arguments, API responses.

---

## How a Future Provider Can Be Added

1. **Add the enum value** in `app/llm/config.py`:
   ```python
   class LLMProvider(str, Enum):
       OPENAI = "openai"
       ANTHROPIC = "anthropic"   # add this
   ```

2. **Add the model allowlist** in `app/llm/config.py`:
   ```python
   ALLOWED_MODELS = {
       LLMProvider.OPENAI: frozenset({...}),
       LLMProvider.ANTHROPIC: frozenset({"claude-3-5-sonnet-20241022", ...}),
   }
   ```

3. **Create the provider** at `app/llm/providers/anthropic_provider.py`:
   ```python
   from app.llm.providers.base import BaseLLMProvider
   
   class AnthropicProvider(BaseLLMProvider):
       @property
       def provider_name(self) -> str:
           return "anthropic"
       
       def get_chat_model(self, config: LLMConfig) -> BaseChatModel:
           from langchain_anthropic import ChatAnthropic
           return ChatAnthropic(
               model=config.model,
               temperature=config.temperature,
               api_key=config.api_key,
           )
   ```

4. **Register it** in `app/llm/factory.py`:
   ```python
   from app.llm.providers.anthropic_provider import AnthropicProvider
   
   _REGISTRY = {
       LLMProvider.OPENAI: OpenAIProvider(),
       LLMProvider.ANTHROPIC: AnthropicProvider(),
   }
   ```

5. **Add the API key** to `Settings` and `.env.example`:
   ```python
   anthropic_api_key: str = ""
   ```

**No other file changes required.** Engine, planner, content service, and config interpreter all continue to work through the gateway without modification.

---

## Which Existing Components Use the Gateway

| Component | File | Gateway call |
|---|---|---|
| DynamicAgentEngine | `app/core/engine.py` | `get_llm_gateway().get_chat_model_for_role(blueprint.llm_model, temperature=0)` |
| Planner — plan generation | `app/services/planner.py` | `get_llm_gateway().get_chat_model(temperature=0)` |
| Planner — response synthesis | `app/services/planner.py` | `get_llm_gateway().get_chat_model(temperature=0)` |
| Content service | `app/services/content_service.py` | `get_llm_gateway().get_chat_model(temperature=0.7)` |
| Config interpreter | `app/services/config_interpreter.py` | `get_llm_gateway().get_chat_model_for_role(role_llm_model=llm_model, temperature=0)` |

The embedding calls in `vector_store.py` and `document_processor.py` use the raw `openai.AsyncOpenAI` client directly. These are **intentionally not routed through the LLM Gateway** — they are embedding operations (not chat completions) and follow a different API surface. This is documented as a known limitation below.

---

## Health / Configuration Check

```
GET /api/v1/llm/status
Headers: X-Tenant-ID: <tenant>
```

Returns:
```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key_present": true,
  "is_ready": true,
  "error": null,
  "allowed_models": ["gpt-3.5-turbo", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"]
}
```

- Does **not** make a live OpenAI API call — safe to poll
- Never returns the API key value
- `api_key_present: true` means a key is configured — it does **not** confirm the key is valid

---

## What Is Intentionally NOT Implemented in Phase 1

| Capability | Status | Notes |
|---|---|---|
| OpenAI provider | **IMPLEMENTED** | Full ChatOpenAI support |
| Anthropic provider | PLANNED | Architecture is ready; add AnthropicProvider |
| Google provider | PLANNED | Architecture is ready; add GoogleProvider |
| Local/self-hosted models | PLANNED | Implement via a custom BaseLLMProvider |
| Embedding gateway | PLANNED | `vector_store.py` / `document_processor.py` use raw `AsyncOpenAI` directly |
| Per-tenant API keys | PLANNED | Gateway currently uses one key from Settings |
| MCP integration | PLANNED | Phase N |
| Dynamic tool creation | PLANNED | Phase N |
| Dynamic AI employee creation | PLANNED | Phase N |
| Streaming responses | PLANNED | Gateway can be extended with `.astream()` support |

---

## Database Changes

**None.** The existing `RoleConfiguration.llm_model` column (added in migration `a3f2c8e91d04`) is sufficient. No new tables were created.

The only schema change is the addition of the optional `llm_model` field to `AgentBlueprint` (a Pydantic model, not persisted). This is backward-compatible — existing blueprints without the field default to `None`, which the engine resolves to `settings.llm_default_model`.

---

## Known Limitations

1. **Embeddings are not routed through the gateway.** `text-embedding-3-small` calls in `vector_store.py` and `document_processor.py` continue to use `openai.AsyncOpenAI` directly. A separate embedding abstraction layer is recommended for Phase N.

2. **Single API key.** The gateway uses one `OPENAI_API_KEY` from `Settings`. Per-tenant key management is not implemented.

3. **No live connectivity test.** `gateway.health()` checks configuration only — it does not confirm the key is accepted by OpenAI. Implement an explicit connectivity test if a startup ping is needed.

4. **`monitoring_engine.py` does not pass `llm_model` to `AgentBlueprint`.** The monitoring engine builds blueprints from role configuration but does not yet wire `role_config.llm_model` into the blueprint. This means triggered monitoring plans always use the application default model. This can be added in Phase N without changing the gateway.

5. **`blueprint.llm_model` is not validated at the schema layer.** `AgentBlueprint.llm_model` accepts any string (or `None`) — validation only fires at the gateway layer when `get_chat_model_for_role()` is called. This is intentional: the schema should remain model-agnostic; the gateway is the right place for allowlist enforcement.
