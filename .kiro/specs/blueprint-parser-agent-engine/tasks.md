# Implementation Tasks

## Blueprint Parser & Dynamic Agent Engine

- [x] 1. Implement `AgentBlueprint` and `AgentExecutionRequest` Pydantic v2 models in `app/schemas/blueprint.py`
  - `AgentBlueprint` with `agent_id`, `role_name`, `system_persona`, `allowed_tools`, `guarded_tools`, `tenant_id`
  - `min_length=1` on string fields; `field_validator` enforcing list type on tool arrays
  - `AgentExecutionRequest` wrapping blueprint + non-empty `user_prompt` + optional `session_id`
  - `AgentExecutionResponse` with `message`, `tool_calls`, `sources`, `requires_approval`, `session_id`
  - **Files:** `backend/app/schemas/blueprint.py`

- [x] 2. Implement `MASTER_TOOL_REGISTRY` and `resolve_tools` in `app/tools/registry.py`
  - Define `query_sales_db`, `fetch_knowledge_base`, `send_email`, `query_campaign_analytics`, `generate_report` as `@tool`-decorated functions
  - Expose as module-level `MASTER_TOOL_REGISTRY` dict
  - `resolve_tools(names)` raises `ValueError` for unrecognised keys, returns ordered callable list
  - **Files:** `backend/app/tools/registry.py`

- [x] 3. Implement `DynamicAgentEngine` in `app/core/engine.py`
  - `__init__` resolves tools, creates `ChatOpenAI(model="gpt-4o-mini")`, calls `.bind_tools()`
  - `execute` builds `[SystemMessage, HumanMessage]`, calls `ainvoke`, extracts `tool_calls`, sets `requires_approval` for guarded tools
  - Raises `ValueError` (propagated from `resolve_tools`) before any LLM binding on unknown tool
  - **Files:** `backend/app/core/engine.py`

- [x] 4. Implement the FastAPI execution router in `app/api/routers/execution.py`
  - `POST /api/v1/agent/execute` accepting `AgentExecutionRequest`
  - Maps `ValueError` → HTTP 400 with descriptive message
  - Maps unexpected exceptions → HTTP 500 without stack trace
  - Returns `AgentExecutionResponse`
  - **Files:** `backend/app/api/routers/execution.py`

- [x] 5. Register execution router and verify service structure
  - Router mounted in `app/main.py`
  - `requirements.txt` includes pinned `fastapi`, `pydantic`, `langchain-core`, `langchain-openai`, `openai`
  - **Files:** `backend/app/main.py`, `backend/requirements.txt`

- [x] 6. Wire frontend `useAgentExecute` hook to send full `AgentExecutionRequest`
  - Export `AgentBlueprint`, `AgentExecutionRequest`, `AgentExecutionResponse` TypeScript interfaces
  - Export `DEFAULT_BLUEPRINT` for the Digital Marketing Manager role
  - Update `useAgentExecute` mutationFn to pass `{ blueprint, user_prompt, session_id }` to backend
  - **Files:** `src/hooks/use-api.ts`

- [x] 7. Wire `MailBox` component to `useAgentExecute` hook
  - Replace direct `mailService.send` AI response with `useAgentExecute.mutate`
  - Pass `DEFAULT_BLUEPRINT` and stable `sessionId`
  - Show "Thinking…" pulse while pending; prefix reply with approval label when `requires_approval=true`
  - Disable input and send button while pending
  - **Files:** `src/components/eaawp/MailBox.tsx`

- [x] 8. Wire Meeting Room prompt to `useAgentExecute` hook
  - Call `useAgentExecute.mutate` on prompt submit
  - Display agent reply in a styled panel below the submitted prompt
  - Disable input while pending
  - **Files:** `src/routes/meeting.tsx`
