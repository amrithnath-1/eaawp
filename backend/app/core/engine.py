"""
EAAWP Dynamic Agent Engine

DynamicAgentEngine is the execution kernel for a single agent invocation.
It accepts a validated AgentBlueprint, resolves only its permitted tools
from MASTER_TOOL_REGISTRY, binds them to the LLM via .bind_tools(), and
executes a user prompt with the system persona prepended.

Structural scope guarantee
--------------------------
If a tool key is absent from blueprint.allowed_tools, its function schema
is NEVER present in the tool definitions sent to the LLM. This is enforced
by the resolve_tools() call which returns only the explicitly allowed set.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.schemas.blueprint import AgentBlueprint, AgentExecutionResponse, ToolCallDetail
from app.tools.registry import resolve_tools


class DynamicAgentEngine:
    """
    Instantiated once per request. Resolves the agent's permitted tools,
    binds them to the LLM, and provides an execute() coroutine.

    Raises:
        ValueError: During __init__ if any allowed_tool key does not exist
                    in MASTER_TOOL_REGISTRY (propagated from resolve_tools).
    """

    def __init__(self, blueprint: AgentBlueprint) -> None:
        self.blueprint = blueprint

        # Resolve only the tools listed in allowed_tools — nothing else.
        # resolve_tools raises ValueError for any unrecognised key.
        self._tools = resolve_tools(blueprint.allowed_tools)

        # Initialise the LLM and bind the scoped tool set.
        # bind_tools() produces a new model instance; the original is unchanged.
        base_model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self._model = base_model.bind_tools(self._tools) if self._tools else base_model

    async def execute(
        self,
        user_prompt: str,
        session_id: str | None = None,
    ) -> AgentExecutionResponse:
        """
        Invoke the scoped LLM with the system persona and user prompt.

        Args:
            user_prompt: The user's natural-language request.
            session_id:  Optional session identifier for continuity.

        Returns:
            AgentExecutionResponse with the LLM's message content, any
            tool call requests, and metadata.
        """
        resolved_session_id = session_id or str(uuid.uuid4())

        messages = [
            SystemMessage(content=self.blueprint.system_persona),
            HumanMessage(content=user_prompt),
        ]

        response = await self._model.ainvoke(messages)

        # Extract text content
        message_text: str = ""
        if isinstance(response.content, str):
            message_text = response.content
        elif isinstance(response.content, list):
            # Handle structured content blocks (e.g. tool_use + text)
            text_parts = [
                block.get("text", "")
                for block in response.content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            message_text = " ".join(text_parts)

        # Extract tool calls requested by the LLM
        tool_calls: list[ToolCallDetail] = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_calls.append(
                    ToolCallDetail(
                        name=tc.get("name", ""),
                        args=tc.get("args", {}),
                    )
                )

        # A response requires human approval when:
        # 1. It contains tool calls for tools in the blueprint's guarded_tools list, or
        # 2. The LLM explicitly mentions approval in its response.
        guarded_set = set(self.blueprint.guarded_tools)
        requires_approval = any(tc.name in guarded_set for tc in tool_calls)

        return AgentExecutionResponse(
            message=message_text or "(No text response from model)",
            tool_calls=tool_calls,
            sources=[],  # TODO: populate from RAG retrieval context when integrated
            requires_approval=requires_approval,
            session_id=resolved_session_id,
        )
