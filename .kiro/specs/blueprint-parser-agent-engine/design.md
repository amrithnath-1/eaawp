# Design Document

## Blueprint Parser & Dynamic Agent Engine

### Overview

This component is the execution kernel of the EAAWP backend. It enforces tool scoping at the structural level: a `DynamicAgentEngine` instance resolves only the tools listed in a blueprint's `allowed_tools` against a static `MASTER_TOOL_REGISTRY`, binds them to a `ChatOpenAI` instance via `.bind_tools()`, and executes prompts with the agent's system persona prepended. A FastAPI router exposes this as a POST endpoint at `/api/v1/agent/execute`. The frontend's `useAgentExecute` hook calls this endpoint when `VITE_USE_REAL_API=true`, passing the full `AgentBlueprint` alongside the user prompt.

### Architecture

```
Frontend (React)
  └─ useAgentExecute hook  →  POST /api/v1/agent/execute
                                        │
                              FastAPI execution router
                                        │
                              DynamicAgentEngine.__init__
                                        │
                              resolve_tools(allowed_tools)
                                        │
                              MASTER_TOOL_REGISTRY (static dict)
                                        │
                              ChatOpenAI.bind_tools(scoped_tools)
                                        │
                              DynamicAgentEngine.execute(prompt)
                                        │
                              AgentExecutionResponse
```

### Components

#### `app/schemas/blueprint.py`

- `AgentBlueprint` — Pydantic v2 model with `agent_id`, `role_name`, `system_persona`, `allowed_tools`, `guarded_tools`, `tenant_id`. Fields with `min_length=1` enforce non-empty strings. A `field_validator` enforces list type on tool arrays.
- `AgentExecutionRequest` — wraps `AgentBlueprint` + `user_prompt` (non-empty) + optional `session_id`.
- `AgentExecutionResponse` — `message`, `tool_calls`, `sources`, `requires_approval`, `session_id`.

#### `app/tools/registry.py`

- `MASTER_TOOL_REGISTRY` — module-level `dict[str, Callable]` mapping tool keys to `@tool`-decorated functions.
- Built-in tools: `query_sales_db`, `fetch_knowledge_base`, `send_email`, `query_campaign_analytics`, `generate_report`.
- `resolve_tools(names)` — iterates `names`, raises `ValueError` for any unknown key, returns ordered list of callables.

#### `app/core/engine.py`

- `DynamicAgentEngine.__init__(blueprint)` — calls `resolve_tools`, builds `ChatOpenAI(model="gpt-4o-mini")`, calls `.bind_tools()`.
- `DynamicAgentEngine.execute(user_prompt, session_id)` — builds `[SystemMessage, HumanMessage]`, calls `model.ainvoke`, parses `tool_calls` from response, sets `requires_approval` for guarded tools.

#### `app/api/routers/execution.py`

- `POST /api/v1/agent/execute` — instantiates engine, calls `execute()`, maps `ValueError` → 400, unexpected errors → 500. No stack traces in response bodies.

#### Frontend: `src/hooks/use-api.ts`

- `AgentBlueprint`, `AgentExecutionRequest`, `AgentExecutionResponse` TypeScript interfaces mirror the Python schemas.
- `DEFAULT_BLUEPRINT` — Digital Marketing Manager blueprint used when no custom blueprint is provided.
- `useAgentExecute()` mutation — sends `{ blueprint, user_prompt, session_id }` to `/api/v1/agent/execute` when `VITE_USE_REAL_API=true`; returns clearly-labelled mock response otherwise.

#### Frontend: `src/components/eaawp/MailBox.tsx`

- Wired to `useAgentExecute` hook. Passes `DEFAULT_BLUEPRINT` and a stable `sessionId` per component mount.
- Shows "Thinking…" pulse while pending; displays `requires_approval` prefix when the response flags guarded tool usage.

#### Frontend: `src/routes/meeting.tsx`

- Meeting Room prompt input calls `useAgentExecute` and displays the agent reply inline below the submitted prompt.

### Data Flow

1. User types a prompt in MailBox or Meeting Room.
2. `useAgentExecute.mutate({ blueprint: DEFAULT_BLUEPRINT, user_prompt, session_id })` is called.
3. If `USE_REAL_API=true`: `POST /api/v1/agent/execute` with JSON body.
4. FastAPI validates request body (422 on failure).
5. `DynamicAgentEngine` resolves tools (400 on unknown tool).
6. LLM invoked with system persona + user prompt.
7. Response includes `message`, `tool_calls`, `requires_approval`, `session_id`.
8. Frontend renders reply; if `requires_approval=true`, prefixes with approval label.

### Security

- Tool scope is enforced structurally: `resolve_tools` raises before any LLM binding if an unknown tool key appears.
- Internal errors are never surfaced in HTTP response bodies.
- `MASTER_TOOL_REGISTRY` is a module-level constant — not mutated at request time.
