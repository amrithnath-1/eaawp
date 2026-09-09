# Requirements Document

## Introduction

The Blueprint Parser & Dynamic Agent Engine is Core Component 1 of the EAAWP (Enterprise Agentic AI Workforce Platform) backend. It is a standalone Python service that accepts JSON agent blueprint definitions, validates and parses them into strongly typed models, resolves only the explicitly permitted tools from a secured master registry, dynamically binds those tools to an LLM instance, and exposes a REST API endpoint that executes agent invocations with full scope enforcement.

This component serves as the trust boundary and execution kernel of the platform: no tool that is absent from a blueprint's `allowed_tools` list may reach the LLM context, and no tool name that is absent from the master registry may be resolved at runtime.

## Glossary

- **Blueprint_Parser**: The component responsible for deserializing and validating incoming JSON agent blueprint payloads into `AgentBlueprint` objects.
- **AgentBlueprint**: A Pydantic v2 model that is the canonical in-memory representation of a parsed agent blueprint.
- **Master_Tool_Registry**: A static Python dictionary (`MASTER_TOOL_REGISTRY`) that maps string tool name keys to LangChain `@tool`-decorated callable functions.
- **Tool_Resolver**: The subsystem within `DynamicAgentEngine` that filters `MASTER_TOOL_REGISTRY` against the tool names declared in an `AgentBlueprint`.
- **DynamicAgentEngine**: The class that instantiates a scoped LLM, resolves permitted tools, binds them to the model, and executes agent prompts.
- **Execution_API**: The FastAPI router exposing the `/api/v1/agent/execute` endpoint.
- **AgentExecutionRequest**: A Pydantic v2 model representing the HTTP request body for the `/api/v1/agent/execute` endpoint.
- **LLM**: The `ChatOpenAI` model instance (`gpt-4o-mini`) used for agent invocations.
- **Tool_Schema**: The JSON schema representation of a `@tool`-decorated function that is passed to the LLM via `.bind_tools()`.
- **Tenant**: An organisation or isolated workspace context identified by `tenant_id` within a blueprint.
- **Guarded_Tool**: A tool name listed in `blueprint.guarded_tools` that requires elevated approval before execution (tracked in the blueprint model but outside the scope of the engine's runtime enforcement in this component).

---

## Requirements

### Requirement 1: JSON Blueprint Parsing

**User Story:** As an EAAWP platform operator, I want incoming agent blueprint JSON objects parsed into a validated, strongly typed `AgentBlueprint` model, so that all downstream engine components operate on guaranteed-structure data and field-level errors are caught at the boundary.

#### Acceptance Criteria

1. THE `Blueprint_Parser` SHALL deserialise a valid JSON object into an `AgentBlueprint` Pydantic v2 model containing the fields: `agent_id` (str), `role_name` (str), `system_persona` (str), `allowed_tools` (List[str]), `guarded_tools` (List[str]), and `tenant_id` (str).
2. WHEN a JSON payload is missing one or more required fields, THE `Blueprint_Parser` SHALL raise a Pydantic `ValidationError` that identifies each missing field by name.
3. WHEN a JSON payload contains a field with an incorrect type (e.g., `allowed_tools` supplied as a plain string instead of a list), THE `Blueprint_Parser` SHALL raise a Pydantic `ValidationError` identifying the offending field and expected type.
4. THE `AgentBlueprint` model SHALL reject empty strings for `agent_id`, `role_name`, `system_persona`, and `tenant_id` fields, raising a `ValidationError` for each empty-string violation.
5. THE `AgentBlueprint` model SHALL permit `allowed_tools` and `guarded_tools` to be empty lists without raising a validation error.
6. FOR ALL valid `AgentBlueprint` objects, serialising the object to a JSON-compatible dictionary and re-parsing that dictionary SHALL produce an `AgentBlueprint` equal to the original (round-trip property).

---

### Requirement 2: Master Tool Registry and Secure Tool Resolution

**User Story:** As a platform security architect, I want all callable tools to be pre-registered in a static master registry and resolved by exact name match, so that arbitrary string-based tool execution is structurally impossible.

#### Acceptance Criteria

1. THE `Master_Tool_Registry` SHALL be a Python dictionary with string keys and LangChain `@tool`-decorated function values, containing at minimum the following three entries: `query_sales_db`, `fetch_knowledge_base`, and `send_email`.
2. THE `query_sales_db` tool SHALL accept a `region` parameter of type `str` and return a `str`.
3. THE `fetch_knowledge_base` tool SHALL accept a `query` parameter of type `str` and return a `str`.
4. THE `send_email` tool SHALL accept a `recipient` parameter of type `str` and a `body` parameter of type `str`, and return a `str`.
5. WHEN the `Tool_Resolver` is called with a tool name that does not exist as a key in `Master_Tool_Registry`, THE `Tool_Resolver` SHALL raise a `ValueError` that includes the unrecognised tool name in its message.
6. WHEN the `Tool_Resolver` is called with a tool name that exists as a key in `Master_Tool_Registry`, THE `Tool_Resolver` SHALL return the corresponding `@tool`-decorated callable without modification.
7. THE `Master_Tool_Registry` SHALL be a module-level constant defined at import time, ensuring its contents cannot be mutated during request processing.

---

### Requirement 3: Dynamic Tool Scoping and LLM Binding

**User Story:** As a platform security architect, I want the `DynamicAgentEngine` to bind only the tools explicitly listed in a blueprint's `allowed_tools` to the LLM instance, so that tools absent from the blueprint are structurally absent from the LLM context and cannot be invoked.

#### Acceptance Criteria

1. WHEN `DynamicAgentEngine` is initialised with an `AgentBlueprint`, THE `DynamicAgentEngine` SHALL resolve each name in `blueprint.allowed_tools` against `Master_Tool_Registry` and collect the resulting callables as the agent's scoped tool set.
2. WHEN `DynamicAgentEngine` is initialised and `blueprint.allowed_tools` contains a name not present in `Master_Tool_Registry`, THE `DynamicAgentEngine` SHALL raise a `ValueError` before any LLM binding is attempted.
3. THE `DynamicAgentEngine` SHALL call `.bind_tools()` on the `ChatOpenAI` model instance, passing only the resolved scoped tool callables, before any agent invocation is performed.
4. WHEN a tool name is absent from `blueprint.allowed_tools`, THE `DynamicAgentEngine` SHALL ensure that tool's schema is not present in the tool definitions submitted to the LLM during invocation.
5. WHEN `blueprint.allowed_tools` is an empty list, THE `DynamicAgentEngine` SHALL bind an empty tool set to the LLM instance without raising an error.
6. THE `DynamicAgentEngine` SHALL initialise the `ChatOpenAI` instance with `model="gpt-4o-mini"`.
7. WHEN the `DynamicAgentEngine` executes a prompt, THE `DynamicAgentEngine` SHALL prepend the `blueprint.system_persona` value as the system message to the LLM invocation.
8. FOR ALL valid `AgentBlueprint` objects, the set of tool schemas bound to the LLM SHALL be exactly equal to the set of tools whose names appear in `blueprint.allowed_tools` and no others (structural scope guarantee).

---

### Requirement 4: FastAPI Execution Endpoint

**User Story:** As a frontend or integration developer, I want a POST endpoint that accepts a blueprint and a user prompt and returns the LLM's invocation response, so that agent execution can be triggered over HTTP without knowledge of the engine internals.

#### Acceptance Criteria

1. THE `Execution_API` SHALL expose a POST endpoint at the path `/api/v1/agent/execute`.
2. THE `Execution_API` SHALL accept a JSON request body conforming to the `AgentExecutionRequest` model, which contains `blueprint` (of type `AgentBlueprint`) and `user_prompt` (of type `str`).
3. WHEN a valid `AgentExecutionRequest` is received, THE `Execution_API` SHALL instantiate a new `DynamicAgentEngine` per request using the `blueprint` from the request body.
4. WHEN a valid `AgentExecutionRequest` is received, THE `Execution_API` SHALL invoke the `DynamicAgentEngine` with `user_prompt` and return the LLM response as the HTTP response body.
5. WHEN the LLM response contains tool call requests, THE `Execution_API` SHALL include those tool call details in the response body without suppression.
6. IF the `AgentExecutionRequest` body fails Pydantic validation, THEN THE `Execution_API` SHALL return an HTTP 422 Unprocessable Entity response containing field-level validation error details.
7. IF `DynamicAgentEngine` initialisation raises a `ValueError` (e.g., due to an unrecognised tool name in the blueprint), THEN THE `Execution_API` SHALL return an HTTP 400 Bad Request response with a descriptive error message.
8. THE `Execution_API` SHALL not expose internal Python stack traces or exception objects in HTTP error response bodies returned to the caller.
9. WHEN `user_prompt` is an empty string, THE `Execution_API` SHALL return an HTTP 422 Unprocessable Entity response indicating the field is required and non-empty.

---

### Requirement 5: Service Structure and Modularity

**User Story:** As a backend developer, I want the service code to follow the prescribed file architecture, so that each concern is isolated in its own module and the codebase is straightforward to extend with additional tools or engine behaviours.

#### Acceptance Criteria

1. THE Python service SHALL organise source files under an `app/` directory following this structure: `app/schemas/blueprint.py` for Pydantic models, `app/tools/registry.py` for `MASTER_TOOL_REGISTRY` and `@tool` functions, `app/core/engine.py` for `DynamicAgentEngine`, and `app/api/routers/execution.py` for the FastAPI router.
2. THE `MASTER_TOOL_REGISTRY` SHALL be importable from `app.tools.registry` without side effects.
3. THE `DynamicAgentEngine` class SHALL be importable from `app.core.engine` without side effects.
4. THE `AgentBlueprint` and `AgentExecutionRequest` models SHALL be importable from `app.schemas.blueprint` without side effects.
5. THE Python service SHALL include a `requirements.txt` or `pyproject.toml` listing pinned versions of `fastapi`, `pydantic` (v2), `langchain-core`, `langchain-openai`, and `openai` as direct dependencies.
