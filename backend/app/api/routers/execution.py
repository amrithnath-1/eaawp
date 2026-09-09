"""
EAAWP Execution Router

POST /api/v1/agent/execute

Accepts an AgentExecutionRequest, instantiates DynamicAgentEngine per request,
and returns the scoped agent's LLM response.

Error mapping
-------------
422  Pydantic validation failure (FastAPI handles automatically)
400  ValueError from DynamicAgentEngine (unknown tool in blueprint)
500  Unexpected engine / LLM failure
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.core.engine import DynamicAgentEngine
from app.schemas.blueprint import AgentExecutionRequest, AgentExecutionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post(
    "/execute",
    response_model=AgentExecutionResponse,
    summary="Execute an agent prompt against a scoped blueprint",
)
async def execute_agent(request: AgentExecutionRequest) -> AgentExecutionResponse:
    """
    Instantiate a DynamicAgentEngine from the supplied blueprint and invoke
    it with the user's prompt.

    - 422 if the request body fails Pydantic validation (automatic).
    - 400 if the blueprint references a tool not in MASTER_TOOL_REGISTRY.
    - 500 on unexpected LLM or engine errors.

    Internal stack traces are never exposed in the response body.
    """
    try:
        engine = DynamicAgentEngine(blueprint=request.blueprint)
    except ValueError as exc:
        logger.warning("Blueprint tool resolution failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return await engine.execute(
            user_prompt=request.user_prompt,
            session_id=request.session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent execution failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Agent execution failed. Please try again.",
        ) from exc
