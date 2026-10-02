"""
EAAWP Execution Router

POST /api/v1/agent/execute

Two execution modes:
  1. Simple execution  — no action tools in blueprint → existing engine loop
  2. Planning mode     — action tools present → multi-step planner

For planning mode the planner:
  - Generates a structured plan via LLM
  - Executes read steps (query_company_data, fetch_knowledge_base, etc.)
  - Routes action steps through governance (approval if needed)
  - Pauses and returns "awaiting_approval" when human approval is needed
  - Synthesises a final response

For simple mode the existing DynamicAgentEngine loop is used unchanged.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.registry import is_action_tool
from app.config import settings
from app.core.auth import get_optional_tenant_id
from app.core.engine import DynamicAgentEngine
from app.core.prompt_guard import validate_user_prompt
from app.db.session import get_db
from app.schemas.blueprint import AgentExecutionRequest, AgentExecutionResponse
from app.services.dmm_context import COMPANY_DATA_TOOL_KEY, build_data_context_block
from app.services.vector_store import ScoredChunk, retrieve_similar_chunks
from app.tools.registry import clear_tool_context, set_tool_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _tenant_optional(x_tenant_id: str = Header(default="default-tenant", alias="X-Tenant-ID")) -> str:
    return x_tenant_id


@router.post(
    "/execute",
    response_model=AgentExecutionResponse,
    summary="Execute an agent prompt — simple or multi-step planned",
)
async def execute_agent(
    request: AgentExecutionRequest,
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AgentExecutionResponse:

    # Determine if any action tools are in the blueprint
    has_action_tools = any(
        is_action_tool(t) for t in request.blueprint.allowed_tools
    )

    # Phase P — prompt injection guard
    validate_user_prompt(request.user_prompt)

    resolved_session_id = request.session_id or str(uuid.uuid4())
    role_key = _blueprint_role_key(request.blueprint.role_name)

    # ── Server-side blueprint override ────────────────────────────────────────
    # The client supplies the role_name and user_prompt but MUST NOT be trusted
    # for allowed_tools, guarded_tools, tenant_id, or system_persona.  Those
    # are always loaded from the DB RoleConfiguration for the authenticated
    # tenant.  This prevents privilege escalation via a crafted blueprint.
    from app.api.routers.role_config import _get_or_seed, _orm_to_schema
    try:
        role_row = await _get_or_seed(role_key, tenant_id, db)
        server_config = _orm_to_schema(role_row)
        server_allowed: list[str] = server_config.allowed_tools
        server_guarded: list[str] = server_config.guarded_tools
        server_persona: str = server_config.system_persona or request.blueprint.system_persona
        server_llm: str | None = server_config.llm_model or request.blueprint.llm_model
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not load server-side role config for %s/%s: %s — "
            "falling back to empty tool list for safety",
            tenant_id, role_key, exc,
        )
        server_allowed = []
        server_guarded = []
        server_persona = request.blueprint.system_persona
        server_llm = request.blueprint.llm_model

    # Replace the client-supplied blueprint fields with verified server values.
    authoritative_blueprint = request.blueprint.model_copy(update={
        "tenant_id": tenant_id,          # always from JWT, never from request body
        "allowed_tools": server_allowed,
        "guarded_tools": server_guarded,
        "system_persona": server_persona,
        "llm_model": server_llm,
    })

    has_action_tools = any(is_action_tool(t) for t in authoritative_blueprint.allowed_tools)

    # ── Shared pre-work: RAG + data context ───────────────────────────────────
    rag_chunks: list[ScoredChunk] = []
    if "fetch_knowledge_base" in authoritative_blueprint.allowed_tools:
        try:
            # Gemini embeddings — no OpenAI client required
            rag_chunks = await retrieve_similar_chunks(
                query=request.user_prompt,
                tenant_id=authoritative_blueprint.tenant_id,
                role_scope=role_key,
                db=db,
                top_k=4,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG retrieval failed: %s", exc)

    data_context_block = ""
    if COMPANY_DATA_TOOL_KEY in authoritative_blueprint.allowed_tools:
        try:
            data_context_block = await build_data_context_block(
                tenant_id=authoritative_blueprint.tenant_id,
                db=db,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Data context build failed: %s", exc)

    # ── Phase 3: resolve dynamic integration tools for this tenant/role ───────
    from app.tools.dynamic_tool import build_dynamic_tool_adapter, get_available_tools

    dynamic_tool_map: dict = {}
    dynamic_tool_keys: list[str] = []
    try:
        dynamic_defns = await get_available_tools(
            tenant_id=authoritative_blueprint.tenant_id,
            role_key=role_key,
            db=db,
        )
        for defn in dynamic_defns:
            adapter = build_dynamic_tool_adapter(defn)
            dynamic_tool_map[defn.tool_key] = adapter
            dynamic_tool_keys.append(defn.tool_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dynamic tool resolution failed (non-fatal): %s", exc)

    augmented_allowed = list(authoritative_blueprint.allowed_tools) + [
        k for k in dynamic_tool_keys
        if k not in authoritative_blueprint.allowed_tools
    ]
    augmented_blueprint = authoritative_blueprint.model_copy(
        update={"allowed_tools": augmented_allowed}
    )

    set_tool_context(
        db_session=db,
        tenant_id=authoritative_blueprint.tenant_id,
        role_key=role_key,
        allowed_tools=augmented_allowed,
        guarded_tools=authoritative_blueprint.guarded_tools,
        dynamic_tools=dynamic_tool_map,
    )

    # ── Phase J: Retrieve relevant memories for context ───────────────────────
    memory_context_block = ""
    try:
        from app.services.memory_service import search_memory
        memories = await search_memory(
            tenant_id=authoritative_blueprint.tenant_id,
            role_key=role_key,
            query=request.user_prompt,
            db=db,
            limit=5,
        )
        if memories:
            mem_lines = []
            for m in memories:
                mem_lines.append(f"• [{m.category}] {m.title}: {m.content[:200]}")
            memory_context_block = (
                "\n\n## Relevant Memory\n"
                "These are relevant past decisions and learnings:\n"
                + "\n".join(mem_lines)
            )
    except Exception as exc:
        logger.debug("Memory retrieval failed (non-fatal): %s", exc)

    try:
        if has_action_tools:
            # ── Planning mode ─────────────────────────────────────────────────
            from app.services.planner import create_and_execute_plan

            rag_text = ""
            if rag_chunks:
                from app.core.engine import _build_rag_context
                rag_text = _build_rag_context(rag_chunks)

            try:
                final_message, plan_id, all_tool_calls = await create_and_execute_plan(
                    user_prompt=request.user_prompt,
                    blueprint=augmented_blueprint,
                    session_id=resolved_session_id,
                    db=db,
                    system_persona=augmented_blueprint.system_persona,
                    data_context_block=data_context_block,
                    rag_context=rag_text,
                )

                # Fetch plan status for response
                plan_status = None
                step_summaries: list[str] = []
                if plan_id:
                    from sqlalchemy import select
                    from app.db.models import ExecutionPlan, PlanStep
                    pr = await db.execute(
                        select(ExecutionPlan).where(
                            ExecutionPlan.id == plan_id,
                            ExecutionPlan.tenant_id == tenant_id,  # tenant-scoped
                        )
                    )
                    db_plan = pr.scalar_one_or_none()
                    if db_plan:
                        plan_status = db_plan.status
                    sr = await db.execute(
                        select(PlanStep)
                        .where(PlanStep.plan_id == plan_id)
                        .order_by(PlanStep.step_index)
                    )
                    step_summaries = [
                        f"[{s.step_type.upper()}] {s.description} → {s.status}"
                        for s in sr.scalars().all()
                    ]

                guarded_set = set(augmented_blueprint.guarded_tools)
                requires_approval = (
                    plan_status == "awaiting_approval"
                    or any(tc.name in guarded_set for tc in all_tool_calls)
                )

                # Data sources from query_company_data results
                from app.services.dmm_context import build_data_source_metadata
                data_sources: list[str] = []
                for tc in all_tool_calls:
                    if tc.name == "query_company_data":
                        data_sources.extend(build_data_source_metadata(final_message))
                rag_sources = [c.document_name for c in rag_chunks if c.document_name]
                combined_sources = list(dict.fromkeys(rag_sources + data_sources))

                return AgentExecutionResponse(
                    message=final_message,
                    tool_calls=all_tool_calls,
                    sources=combined_sources,
                    requires_approval=requires_approval,
                    session_id=resolved_session_id,
                    plan_id=plan_id or None,
                    plan_status=plan_status,
                    step_summaries=step_summaries,
                )

            except Exception as exc:  # noqa: BLE001
                logger.exception("Planning execution failed: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail="Agent planning execution failed. Please try again.",
                ) from exc

        else:
            # ── Simple execution mode ─────────────────────────────────────────
            try:
                engine = DynamicAgentEngine(blueprint=augmented_blueprint)
            except ValueError as exc:
                logger.warning("Blueprint tool resolution failed: %s", exc)
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            try:
                resp = await engine.execute(
                    user_prompt=request.user_prompt,
                    session_id=resolved_session_id,
                    rag_chunks=rag_chunks if rag_chunks else None,
                    data_context_block=data_context_block + memory_context_block,
                )
                # Carry plan fields as None for simple mode
                # ── Phase J: Store execution in memory ─────────────────────────
                try:
                    from app.services.memory_service import store_memory
                    await store_memory(
                        tenant_id=authoritative_blueprint.tenant_id,
                        role_key=role_key,
                        category="execution_history",
                        title=request.user_prompt[:100],
                        content=resp.message[:500],
                        db=db,
                        confidence=0.8,
                    )
                except Exception as mem_exc:
                    logger.debug("Memory storage failed (non-fatal): %s", mem_exc)

                return AgentExecutionResponse(
                    message=resp.message,
                    tool_calls=resp.tool_calls,
                    sources=resp.sources,
                    requires_approval=resp.requires_approval,
                    session_id=resp.session_id,
                    plan_id=None,
                    plan_status=None,
                    step_summaries=[],
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent execution failed: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail="Agent execution failed. Please try again.",
                ) from exc

    finally:
        clear_tool_context()


def _blueprint_role_key(role_name: str) -> str:
    mapping = {
        "Digital Marketing Manager": "DIGITAL_MARKETING_MANAGER",
        "Sales Development Rep": "SALES_DEVELOPMENT_REP",
        "Financial Analyst": "FINANCIAL_ANALYST",
        "HR Business Partner": "HR_BUSINESS_PARTNER",
        "Customer Success Manager": "CUSTOMER_SUCCESS_MANAGER",
        "Operations Analyst": "OPERATIONS_ANALYST",
        "Data Intelligence Analyst": "DATA_INTELLIGENCE_ANALYST",
    }
    return mapping.get(role_name, "DIGITAL_MARKETING_MANAGER")
