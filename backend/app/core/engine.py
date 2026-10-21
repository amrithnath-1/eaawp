"""
EAAWP Dynamic Agent Engine

DynamicAgentEngine is the execution kernel for a single agent invocation.
It accepts a validated AgentBlueprint, resolves only its permitted tools
from MASTER_TOOL_REGISTRY, binds them to the LLM via .bind_tools(), and
executes a user prompt with the system persona prepended.

LLM is obtained through the LLM Gateway (app.llm) — model selection is
centrally validated; this engine never creates a ChatOpenAI instance directly.

Data-Aware DMM
--------------
When query_company_data is in the blueprint's allowed_tools, the engine
injects a data-context block into the system message that lists the
available semantic concepts (resolved from the tenant's semantic mappings).
The LLM is instructed to use query_company_data for structured queries and
how to handle missing mappings, denied entities, and empty results.

Tool call execution loop
------------------------
After the initial LLM response, if the model requested tool calls, the
engine executes them and sends the results back to the LLM for a final
synthesised response. This allows the DMM to actually use the data it
retrieves rather than just producing a tool call stub.

RAG integration
---------------
When a KnowledgeRetriever is provided, relevant document chunks are
prepended to the user message before the LLM is invoked. RAG and company
data access can be combined in the same response.

Structural scope guarantee
--------------------------
If a tool key is absent from blueprint.allowed_tools, its function schema
is NEVER present in the tool definitions sent to the LLM.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.llm import get_llm_gateway
from app.schemas.blueprint import AgentBlueprint, AgentExecutionResponse, ToolCallDetail
from app.tools.registry import MASTER_TOOL_REGISTRY, _dynamic_tools_ctx, resolve_tools

if TYPE_CHECKING:
    from app.services.vector_store import ScoredChunk


class DynamicAgentEngine:
    """
    Instantiated once per request. Resolves the agent's permitted tools,
    binds them to the LLM, and provides an execute() coroutine.

    LLM is obtained through the LLM Gateway (app.llm.get_llm_gateway) so
    model selection is centrally validated and never hardcoded at this site.

    Raises:
        ValueError: During __init__ if any allowed_tool key does not exist
                    in MASTER_TOOL_REGISTRY (propagated from resolve_tools).
    """

    def __init__(self, blueprint: AgentBlueprint) -> None:
        self.blueprint = blueprint
        # ── Resolve tools: static registry first, then per-request dynamic map ──
        # _dynamic_tools_ctx is a ContextVar populated by the execution router
        # with tenant-scoped, per-request adapters. It is never a global singleton.
        # Static tools always take precedence over dynamic ones (same key = static wins).
        _dyn_map: dict[str, Any] = _dynamic_tools_ctx.get() or {}
        self._tools = resolve_tools(blueprint.allowed_tools, dynamic_tool_map=_dyn_map)
        # ── LLM via Gateway ───────────────────────────────────────────────────
        _gateway = get_llm_gateway()
        base_model = _gateway.get_chat_model_for_role(
            role_llm_model=blueprint.llm_model,
            temperature=0,
        )
        self._model = base_model.bind_tools(self._tools) if self._tools else base_model
        # Build lookup of tool callables by name for the execution loop.
        # Includes both static registry entries and dynamic tool adapters.
        self._tool_map: dict[str, Any] = {}
        for name in blueprint.allowed_tools:
            if name in MASTER_TOOL_REGISTRY:
                self._tool_map[name] = MASTER_TOOL_REGISTRY[name]
            elif name in _dyn_map:
                self._tool_map[name] = _dyn_map[name]

    async def execute(
        self,
        user_prompt: str,
        session_id: str | None = None,
        rag_chunks: "list[ScoredChunk] | None" = None,
        data_context_block: str = "",
    ) -> AgentExecutionResponse:
        """
        Invoke the scoped LLM, execute any tool calls, then return the final response.

        Args:
            user_prompt:         The user's natural-language request.
            session_id:          Optional session identifier for continuity.
            rag_chunks:          Pre-retrieved RAG knowledge chunks.
            data_context_block:  Injected company data context (available concepts).
        """
        resolved_session_id = session_id or str(uuid.uuid4())

        # ── Build system message ──────────────────────────────────────────────
        system_content = self.blueprint.system_persona
        if data_context_block:
            system_content = system_content + "\n\n" + data_context_block

        # ── Build user message ────────────────────────────────────────────────
        rag_sources: list[str] = []
        if rag_chunks:
            context_block = _build_rag_context(rag_chunks)
            rag_sources = list({c.document_name for c in rag_chunks if c.document_name})
            full_prompt = f"{context_block}\n\nUser question: {user_prompt}"
        else:
            full_prompt = user_prompt

        messages: list[Any] = [
            SystemMessage(content=system_content),
            HumanMessage(content=full_prompt),
        ]

        # ── First LLM call ────────────────────────────────────────────────────
        response = await self._model.ainvoke(messages)

        # ── Tool execution loop ───────────────────────────────────────────────
        # Execute tool calls and feed results back for a final synthesised reply.
        all_tool_calls: list[ToolCallDetail] = []
        data_sources: list[str] = []
        max_iterations = 3  # guard against infinite loops

        for _ in range(max_iterations):
            raw_tool_calls = getattr(response, "tool_calls", None) or []
            if not raw_tool_calls:
                break

            # Record tool calls for the response
            for tc in raw_tool_calls:
                all_tool_calls.append(ToolCallDetail(
                    name=tc.get("name", ""),
                    args=tc.get("args", {}),
                ))

            # Execute each tool and collect results
            messages.append(response)  # AIMessage with tool_calls
            for tc in raw_tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", str(uuid.uuid4()))

                result_text = await _execute_tool(tool_name, tool_args, self._tool_map)

                # Extract data sources from company data tool results
                if tool_name == "query_company_data":
                    from app.services.dmm_context import build_data_source_metadata
                    data_sources.extend(build_data_source_metadata(result_text))

                messages.append(ToolMessage(
                    content=result_text,
                    tool_call_id=tool_call_id,
                ))

            # Second LLM call to synthesise tool results
            response = await self._model.ainvoke(messages)

        # ── Extract final text ────────────────────────────────────────────────
        message_text: str = ""
        if isinstance(response.content, str):
            message_text = response.content
        elif isinstance(response.content, list):
            text_parts = [
                block.get("text", "")
                for block in response.content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            message_text = " ".join(text_parts)

        # Strip fake audit log prefixes the LLM may hallucinate from persona language
        if message_text:
            import re as _re
            _lines = message_text.split("\n")
            _cleaned = [
                ln for ln in _lines
                if not _re.match(
                    r"^\[AUDIT\s?LOG|^\[Action:|^INT-\d|^\[Data Source:|^\[Audit\]|^\[LOG\]",
                    ln.strip(), _re.IGNORECASE,
                )
            ]
            message_text = "\n".join(_cleaned).strip() or message_text.strip()

        # ── Combine all sources ───────────────────────────────────────────────
        combined_sources = list(dict.fromkeys(rag_sources + data_sources))

        # ── Approval check ────────────────────────────────────────────────────
        guarded_set = set(self.blueprint.guarded_tools)
        requires_approval = any(tc.name in guarded_set for tc in all_tool_calls)

        return AgentExecutionResponse(
            message=message_text or "(No text response from model)",
            tool_calls=all_tool_calls,
            sources=combined_sources,
            requires_approval=requires_approval,
            session_id=resolved_session_id,
        )


# ── Tool execution ────────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    tool_args: dict,
    tool_map: dict[str, Any],
) -> str:
    """
    Execute a single tool call and return its string result.
    Handles both sync and async tools. Never raises — errors are returned as text.
    """
    tool_fn = tool_map.get(tool_name)
    if tool_fn is None:
        return f"[ERROR] Tool '{tool_name}' is not available in this agent's scope."

    try:
        from app.tools.dynamic_tool import is_dynamic_tool_key

        if is_dynamic_tool_key(tool_name):
            # Integration tools take ONE JSON-object string.  Never unwrap a
            # single-key dict here: {"property_id": "42"} must reach the tool
            # as JSON, not as the bare value "42".
            if isinstance(tool_args, dict) and set(tool_args) == {"params_json"}:
                payload = tool_args["params_json"]
                payload = payload if isinstance(payload, str) else json.dumps(payload)
            else:
                payload = json.dumps(tool_args if isinstance(tool_args, dict) else {})
            return str(await tool_fn.ainvoke({"params_json": payload}))

        # LangChain @tool functions expose .invoke() for sync and .ainvoke() for async
        if hasattr(tool_fn, "ainvoke"):
            # Build the argument — LangChain tools accept a single string or dict
            if isinstance(tool_args, dict) and len(tool_args) == 1:
                arg_val = next(iter(tool_args.values()))
            elif isinstance(tool_args, dict):
                # For multi-arg tools, pass as JSON string (query_company_data pattern)
                arg_val = json.dumps(tool_args) if tool_args else "{}"
            else:
                arg_val = str(tool_args)

            result = await tool_fn.ainvoke(arg_val)
        else:
            if isinstance(tool_args, dict) and len(tool_args) == 1:
                arg_val = next(iter(tool_args.values()))
            elif isinstance(tool_args, dict):
                arg_val = json.dumps(tool_args) if tool_args else "{}"
            else:
                arg_val = str(tool_args)

            result = tool_fn.invoke(arg_val)

        return str(result) if result is not None else ""
    except Exception as exc:  # noqa: BLE001
        return f"[TOOL ERROR] {tool_name}: {str(exc)[:200]}"


# ── RAG context builder ───────────────────────────────────────────────────────

def _build_rag_context(chunks: "list[ScoredChunk]") -> str:
    lines = [
        "## Company Knowledge Context",
        "The following excerpts have been retrieved from your company's indexed documents.",
        "Use this content to answer the user's question and ALWAYS cite the source document name.",
        "If the retrieved content does not contain the answer, say so — do NOT invent information.",
        "",
    ]
    for i, chunk in enumerate(chunks, 1):
        source_label = chunk.document_name or f"Document {chunk.document_id[:8]}"
        lines.append(f"[Source {i}: {source_label}]")
        lines.append(chunk.text.strip())
        lines.append("")
    return "\n".join(lines)
