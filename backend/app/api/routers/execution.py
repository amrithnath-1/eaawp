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
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.registry import is_action_tool
from app.config import settings
from app.core.auth import get_current_tenant_id, get_current_user, is_admin_user
from app.db.models import User
from app.core.engine import DynamicAgentEngine
from app.core.prompt_guard import validate_user_prompt
from app.db.session import get_db
from app.schemas.blueprint import AgentExecutionRequest, AgentExecutionResponse
from app.services.dmm_context import COMPANY_DATA_TOOL_KEY, build_data_context_block
from app.services.vector_store import ScoredChunk, retrieve_similar_chunks
from app.tools.registry import clear_tool_context, set_tool_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


_CONNECT_RE = re.compile(
    r"\b(connect|connecting|integrate|link|set ?up|authori[sz]e|enable|disconnect|unlink|remove integration|reconnect)\b"
)
_STATUS_RE = re.compile(
    r"\b(connected|connection|status|capabilit(y|ies)|permissions?|grants?|revoke|integrations?)\b"
    r"|what (all )?(can|could) (i|you|we) do with"
)
_PROVIDER_RE = re.compile(
    r"\b(google search console|search console|gsc|google analytics|analytics|ga4|git ?hub|facebook|meta ads|meta"
    r"|instagram ads|mcp|model context protocol|postgres(ql)?|mysql|mariadb|database)\b"
)
# Asking for data FROM a service, as opposed to managing the connection itself.
_DATA_REQUEST_RE = re.compile(
    r"\b(list|show|get|fetch|give|find|which|what are|how many|review|analy[sz]e|summari[sz]e|report|compare|open)\b"
    r".{0,60}\b(repo\w*|issues?|pull requests?|prs?|commits?|branch(es)?|quer(y|ies)|keywords?|pages?"
    r"|clicks|impressions|traffic|sessions|visitors|users|campaigns?|performance|rows|tables?|data)\b"
)
_READ_ONLY_INTENTS = frozenset({"LIST_INTEGRATIONS", "LIST_CAPABILITIES", "CHECK_STATUS", "TEST_CONNECTION"})


def _simple_conversation_reply(prompt: str, role_name: str, role_key: str | None = None) -> str | None:
    """Answer greetings and basic chat without invoking company data tools."""
    normalized = " ".join(prompt.lower().split()).strip(" .!?,")
    if normalized in {
        "hi", "hello", "hey", "hi there", "hello there", "hey there",
        "good morning", "good afternoon", "good evening",
    }:
        return (
            f"Hi! I’m your {role_name} agent. I can answer using documents in your "
            "company Library and data sources connected in Integrations. What "
            "would you like help with?"
        )
    if normalized in {"thanks", "thank you", "thanks a lot"}:
        return "You’re welcome. What would you like help with next?"
    if normalized in {"what can you do", "what can you help me with", "help"}:
        from app.services.workspaces import get_workspace
        w = get_workspace(role_key) if role_key else None
        if w is not None:
            items = "\n".join(f"- {c}" for c in w.capabilities)
            return (
                f"As your {w.name} I can help with:\n\n{items}\n\n"
                "I answer from your company Library and the data sources an administrator connected, "
                "and anything that changes or sends something waits for human approval. What would you like to start with?"
            )
        return (
            "I can help with questions grounded in your company's uploaded documents "
            "and connected data sources. Tell me what you need to find out."
        )
    return None



async def _enforce_workspace_role(request: AgentExecutionRequest, db: AsyncSession, user: User) -> None:
    """
    An interactive request runs as the AI employee the person selected, never as whichever built-in role the client
    names. A request for a different built-in role is refused (the person must switch workspace first, which is
    audited); custom AI employees built by the company keep working by their own role key.
    """
    from app.services.workspaces import WORKSPACE_KEYS, _selection, get_workspace

    bp = request.blueprint
    requested = bp.role_key if bp.role_key else _blueprint_role_key(bp.role_name)
    if requested not in WORKSPACE_KEYS:
        return
    row = await _selection(db, user)
    if row is None:
        return
    if row.role_key != requested:
        current = get_workspace(row.role_key)
        wanted = get_workspace(requested)
        raise HTTPException(
            status_code=409,
            detail=(f"You are working with the {current.name if current else row.role_key} AI employee. "
                    f"Switch AI employee to {wanted.name if wanted else requested} before asking it."),
        )
    request.blueprint = bp.model_copy(update={"role_key": row.role_key})


async def _resolve_role_key(request: AgentExecutionRequest, tenant_id: str, db: AsyncSession) -> str:
    """The role a request runs as: the named built-in role, or a custom role key only if the company has it."""
    role_key = _blueprint_role_key(request.blueprint.role_name)
    if request.blueprint.role_key and request.blueprint.role_key != role_key:
        from sqlalchemy import select
        from app.db.models import RoleConfiguration as _RC
        _known = (await db.execute(
            select(_RC.role_key).where(_RC.tenant_id == tenant_id, _RC.role_key == request.blueprint.role_key)
        )).scalar_one_or_none()
        if _known:
            role_key = _known
        elif request.blueprint.role_key in _BUILT_IN_ROLE_KEYS:
            role_key = request.blueprint.role_key
    return role_key


_BUILT_IN_ROLE_KEYS = frozenset({"DIGITAL_MARKETING_MANAGER", "DATA_INTELLIGENCE_ANALYST", "INSTITUTIONAL_CLERK",
                                 "MEDICAL_ASSISTANT"})


@router.post(
    "/execute",
    response_model=AgentExecutionResponse,
    summary="Execute an agent prompt — simple or multi-step planned",
)
async def execute_agent_endpoint(
    request: AgentExecutionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """
    Interactive request from the Cabin: runs as the person's selected AI employee, inside one of the person's own
    saved conversations (a new one unless `conversation_id` continues an existing one of the same AI employee).
    The person's message is stored before the run and the answer after it; a failed run is stored as a failure
    notice, so History never shows an exchange that did not happen or hides one that did.
    """
    from app.services import conversations as cs

    await _enforce_workspace_role(request, db, user)
    role_key = await _resolve_role_key(request, tenant_id, db)
    conv = await cs.open_for_turn(db, user, role_key, request.conversation_id, request.user_prompt)
    history = await cs.context_block(db, conv)
    earlier_turns = tuple(await cs.recent_turns(db, conv))
    await cs.add_message(db, conv, "user", request.user_prompt)
    # One conversation = one session: pending setup tasks and plans created by this turn point back to it.
    request = request.model_copy(update={"session_id": conv.id, "conversation_id": conv.id})

    token = cs.turn_history.set(history)
    token_msgs = cs.turn_messages.set(earlier_turns)
    try:
        async with db.begin_nested():
            resp = await execute_agent(request=request, tenant_id=tenant_id, db=db, user=user, interactive=True)
    except HTTPException as exc:
        notice = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else \
            "The request failed before an answer was produced. Nothing was executed. Please try again."
        await cs.add_message(db, conv, "assistant", notice, {"error": True})
        await db.commit()   # keep the record of the attempt; the error still reaches the caller
        raise
    finally:
        cs.turn_history.reset(token)
        cs.turn_messages.reset(token_msgs)

    await cs.add_message(db, conv, "assistant", resp.message, cs.display_meta(resp), plan_id=resp.plan_id)
    return resp.model_copy(update={"conversation_id": conv.id, "session_id": conv.id})


async def execute_agent(
    request: AgentExecutionRequest,
    tenant_id: str,
    db: AsyncSession,
    user: User,
    interactive: bool = False,
) -> AgentExecutionResponse:
    """Run a request as `request.blueprint`'s role. Also used by workflows, meetings and resumed pending tasks."""

    # Determine if any action tools are in the blueprint
    has_action_tools = any(
        is_action_tool(t) for t in request.blueprint.allowed_tools
    )

    # Phase P — prompt injection guard
    validate_user_prompt(request.user_prompt)

    resolved_session_id = request.session_id or str(uuid.uuid4())
    role_key = await _resolve_role_key(request, tenant_id, db)

    from app.services.modules import is_module_active, module_for_role, get_module
    _mod = module_for_role(role_key)
    if _mod and not await is_module_active(db, tenant_id, _mod):
        raise HTTPException(status_code=403, detail=f"The {get_module(_mod).name} module is not activated for your company. A company administrator can activate it from the Marketplace.")

    from app.services.employee_lifecycle import employee_is_blocked as _blocked
    if await _blocked(db, tenant_id, role_key):
        raise HTTPException(status_code=403, detail="This AI employee is paused. An administrator can resume it from the Employees page.")

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
        # Role charter (identity, duties, limits, honesty, staying in role) + the company's saved persona.
        # The client-supplied persona is never used: it could otherwise rewrite who the AI employee is.
        from app.services.role_charter import role_system_prompt
        server_persona: str = await role_system_prompt(db, tenant_id, role_key)
        server_llm: str | None = server_config.llm_model or request.blueprint.llm_model
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not load server-side role config for %s/%s: %s — "
            "falling back to empty tool list for safety",
            tenant_id, role_key, exc,
        )
        from app.services.role_charter import build_role_charter
        server_allowed = []
        server_guarded = []
        server_persona = build_role_charter(role_key, request.blueprint.role_name)
        server_llm = request.blueprint.llm_model

    # Platform administration: an administrator can ask ANY AI employee to change EAAWP itself (company profile,
    # AI employee settings, grants, workflows, approval policies). Always approval-gated; never offered to others.
    # Only in an interactive chat with that administrator: unattended runs (workflows, meetings) never reconfigure EAAWP.
    if interactive and is_admin_user(user) and "customize_eaawp" not in server_guarded:
        server_guarded = [*server_guarded, "customize_eaawp"]
    # Tell the model who it is talking to, so it neither refuses an administrator's settings change nor offers one
    # to someone who cannot make it.
    if interactive:
        from app.services.platform_requests import asker_block
        server_persona = (server_persona + "\n\n" + asker_block(
            getattr(user, "name", "") or "", getattr(user, "role", "") or "", is_admin_user(user),
            "customize_eaawp" in server_guarded)).strip()

    # Replace the client-supplied blueprint fields with verified server values.
    authoritative_blueprint = request.blueprint.model_copy(update={
        "tenant_id": tenant_id,          # always from JWT, never from request body
        "role_key": role_key,
        "allowed_tools": server_allowed,
        "guarded_tools": server_guarded,
        "system_persona": server_persona,
        "llm_model": server_llm,
    })

    # Greetings and simple conversational turns must not be sent through the
    # planner: otherwise the model may invent an unrelated integration lookup.
    if role_key == "MEDICAL_ASSISTANT":
        # Deterministic safety boundary: emergencies, crisis wording and requests for medical advice are answered here,
        # BEFORE any language model is involved.
        from app.services.medical_guard import screen as _medical_screen
        _g = _medical_screen(request.user_prompt)
        if _g is not None:
            return AgentExecutionResponse(
                message=_g.message, tool_calls=[], sources=[], requires_approval=False,
                session_id=resolved_session_id, plan_id=None, plan_status=None, step_summaries=[],
            )

    conversational_reply = _simple_conversation_reply(
        request.user_prompt, authoritative_blueprint.role_name, role_key
    )
    if conversational_reply:
        return AgentExecutionResponse(
            message=conversational_reply,
            tool_calls=[],
            sources=[],
            requires_approval=False,
            session_id=resolved_session_id,
            plan_id=None,
            plan_status=None,
            step_summaries=[],
        )

    # ── Settings changes in plain words (administrators) ──────────────────────
    # "Add Passport Services to our services", "call yourself Mira", "pause the clerk": the customization planner turns
    # the request into exact changes now, and the plan below only proposes them for approval. People never need to
    # know a tool name, and the chat model cannot talk itself out of a request it should handle.
    preset_plan = None
    if interactive and "customize_eaawp" in authoritative_blueprint.guarded_tools:
        from app.services.platform_requests import looks_like_settings_change
        if looks_like_settings_change(request.user_prompt):
            preset_plan, _ask = await _settings_change_plan(request.user_prompt, tenant_id, db)
            if _ask:
                return AgentExecutionResponse(
                    message=_ask, tool_calls=[], sources=[], requires_approval=False,
                    session_id=resolved_session_id, plan_id=None, plan_status=None, step_summaries=[],
                )

    # ── Integration action pre-flight ─────────────────────────────────────────
    # MUST run BEFORE RAG retrieval and BEFORE the planner.
    #
    # Uses two-tier detection:
    # 1. Fast keyword match (no LLM call, always works even when Gemini is rate-limited)
    # 2. LLM intent parse for ambiguous cases
    #
    # This prevents the model from answering "Connect my GSC" with knowledge-base
    # documentation instead of executing the integration flow.
    _INTEGRATION_ACTION_INTENTS = frozenset({
        "CONNECT_INTEGRATION",
        "DISCONNECT_INTEGRATION",
        "LIST_INTEGRATIONS",
        "LIST_CAPABILITIES",
        "GRANT_CAPABILITY",
        "REVOKE_CAPABILITY",
        "CHECK_STATUS",
        "TEST_CONNECTION",
    })

    # Tier 1: keyword-based detection - no LLM call needed.  Only requests that MANAGE a connection (connect,
    # disconnect, status, capabilities, grants) are intercepted here; requests for DATA from a connected service
    # ("list my GitHub repositories", "review Google Analytics traffic") must reach the readiness gate and the
    # planner, which run the granted integration tools.  The LLM intent parser runs only when a provider is named,
    # so ordinary questions are not slowed by an extra model call.
    _prompt_lower = request.user_prompt.lower()
    _has_connect_kw = bool(_CONNECT_RE.search(_prompt_lower))
    _has_status_kw = bool(_STATUS_RE.search(_prompt_lower))
    _has_provider_kw = bool(_PROVIDER_RE.search(_prompt_lower))
    _is_data_request = bool(_DATA_REQUEST_RE.search(_prompt_lower))
    _fast_is_integration_action = _has_provider_kw and (
        _has_connect_kw or (_has_status_kw and not _is_data_request)
    )

    try:
        from app.services.nl_integration_service import (
            build_conversation_reply,
            parse_integration_intent,
        )
        from app.integrations import manager as _int_mgr

        _intent = None
        _use_integration_path = _fast_is_integration_action  # default from keywords

        if preset_plan is None and (_has_provider_kw or "integration" in _prompt_lower):
            try:
                _intent = await parse_integration_intent(request.user_prompt)
                # The model may only pick WHICH management action; it cannot turn a request with no connection or
                # status wording ("give the list of repos in my github") into one.
                if (_intent.intent_type in _INTEGRATION_ACTION_INTENTS and _intent.confidence >= 0.65
                        and (_has_connect_kw or _has_status_kw)):
                    # A data request is never answered with a capability list or status card.
                    if not (_is_data_request and _intent.intent_type in _READ_ONLY_INTENTS):
                        _use_integration_path = True
            except Exception as _llm_exc:
                logger.debug("Intent parse LLM call failed (using keyword fallback): %s", _llm_exc)

        if _use_integration_path and preset_plan is None:
            # If LLM parse failed, synthesise a minimal intent from keywords
            if _intent is None or _intent.intent_type == "UNKNOWN":
                from app.schemas.nl_integration import IntegrationIntent
                # Determine provider from keywords
                _detected_provider = None
                if "search console" in _prompt_lower or " gsc" in _prompt_lower or _prompt_lower.startswith("gsc"):
                    _detected_provider = "google_search_console"
                elif "google analytics" in _prompt_lower or " ga4" in _prompt_lower or " ga " in _prompt_lower:
                    _detected_provider = "google_analytics"
                elif "github" in _prompt_lower:
                    _detected_provider = "github"
                elif "facebook" in _prompt_lower or "meta" in _prompt_lower:
                    _detected_provider = "facebook"
                elif "mcp" in _prompt_lower or "model context" in _prompt_lower:
                    _detected_provider = "mcp"
                elif "postgresql" in _prompt_lower or "postgres" in _prompt_lower:
                    _detected_provider = "postgresql"
                elif "mysql" in _prompt_lower or "mariadb" in _prompt_lower:
                    _detected_provider = "mysql"
                _intent = IntegrationIntent(
                    intent_type="CONNECT_INTEGRATION",
                    provider_type=_detected_provider,
                    confidence=0.85,
                    reasoning="Keyword-based detection",
                )

            # Load current integrations for context (safe metadata — no credentials)
            try:
                _existing = await _int_mgr.list_integrations(
                    tenant_id=authoritative_blueprint.tenant_id, db=db
                )
                _tenant_integrations = [
                    {
                        "id": i.id,
                        "provider_type": i.provider_type,
                        "display_name": i.display_name,
                        "status": i.status,
                        "is_enabled": i.is_enabled,
                        "last_tested_at": i.last_tested_at.isoformat()
                        if i.last_tested_at
                        else None,
                    }
                    for i in _existing
                ]
            except Exception:
                _tenant_integrations = []

            _reply, _next_action, _action_data = await build_conversation_reply(
                intent=_intent,
                tenant_integrations=_tenant_integrations,
                db=db,
                tenant_id=authoritative_blueprint.tenant_id,
            )

            import json as _json
            _meta_sources: list[str] = []
            if _next_action != "NONE":
                _meta_sources.append(
                    f"__integration_action__:{_json.dumps({'next_action': _next_action, 'action_data': _action_data})}"
                )

            logger.info(
                "Integration action intercepted: intent=%s provider=%s action=%s tenant=%s",
                _intent.intent_type,
                _intent.provider_type,
                _next_action,
                authoritative_blueprint.tenant_id,
            )

            return AgentExecutionResponse(
                message=_reply,
                tool_calls=[],
                sources=_meta_sources,
                requires_approval=False,
                session_id=resolved_session_id,
                plan_id=None,
                plan_status=None,
                step_summaries=[f"[INTEGRATION] {_intent.intent_type} → {_next_action}"],
            )

    except Exception as _intent_exc:
        # Intent detection is best-effort — if it fails, continue to normal execution
        logger.warning("Integration intent pre-flight failed: %s", _intent_exc)

    # ── Task readiness gate ───────────────────────────────────────────────────
    # A request that needs an integration which is not set up (OAuth client,
    # authorisation, or this role's read grant) must NOT be answered from the
    # model's memory.  Save it, tell the user exactly what is missing, and let
    # POST /agent/pending-tasks/{id}/resume run it once setup is complete.
    from app.services import task_readiness as _ready

    _assessment = (None if preset_plan is not None
                   else await _ready.first_unmet(request.user_prompt, tenant_id, role_key, db,
                                                 context=_turn_history_text()))
    if _assessment is not None:
        _task = await _ready.save_pending(
            tenant_id=tenant_id, user_id=user.id, role_key=role_key,
            role_name=authoritative_blueprint.role_name,
            session_id=resolved_session_id, prompt=request.user_prompt,
            a=_assessment, db=db,
        )
        _reply, _next, _data = _ready.setup_message(_assessment, is_admin=is_admin_user(user))
        _data = {**_data, "pending_task_id": _task.id}
        import json as _json2
        return AgentExecutionResponse(
            message=_reply,
            tool_calls=[],
            sources=[f"__integration_action__:{_json2.dumps({'next_action': _next, 'action_data': _data})}"],
            requires_approval=False,
            session_id=resolved_session_id,
            plan_id=None,
            plan_status="awaiting_setup",
            step_summaries=[f"[SETUP] {_assessment.state} → {_next}"],
            pending_task_id=_task.id,
        )

    # Approval-gated (guarded) actions count too: a role whose only actions need approval must still go through
    # the planner, otherwise the approval flow can never be reached.
    has_action_tools = any(
        is_action_tool(t) for t in [*authoritative_blueprint.allowed_tools, *authoritative_blueprint.guarded_tools]
    )

    # ── Shared pre-work: RAG + data context ───────────────────────────────────
    rag_chunks: list[ScoredChunk] = []
    if "fetch_knowledge_base" in authoritative_blueprint.allowed_tools:
        try:
            # Gemini embeddings — no OpenAI client required
            from app.services.vector_store import allowed_access_levels
            rag_chunks = await retrieve_similar_chunks(
                query=request.user_prompt,
                tenant_id=authoritative_blueprint.tenant_id,
                role_scope=role_key,
                db=db,
                top_k=4,
                # on behalf of the asker: never more than they could read themselves ("AI only" is for the AI)
                access_levels=allowed_access_levels(user.role, is_admin_user(user), human_direct=False),
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

    # A role whose only tools are granted integrations (e.g. a finance role allowed to read
    # Search Console) must still go through the planner, otherwise those tools are never used.
    has_action_tools = has_action_tools or bool(dynamic_tool_keys)

    set_tool_context(
        db_session=db,
        tenant_id=authoritative_blueprint.tenant_id,
        role_key=role_key,
        allowed_tools=augmented_allowed,
        guarded_tools=authoritative_blueprint.guarded_tools,
        dynamic_tools=dynamic_tool_map,
        user_id=user.id,
        is_admin=is_admin_user(user),
        user_role=user.role or "",
    )

    # ── Phase J: Retrieve relevant memories for context ───────────────────────
    memory_context_block = ""
    try:
        if role_key in PERSONAL_DATA_ROLES:
            raise LookupError("shared memory is disabled for roles that handle personal records")
        from app.services.memory_service import format_memory_block, search_memory
        memories = await search_memory(
            tenant_id=authoritative_blueprint.tenant_id,
            role_key=role_key,
            query=request.user_prompt,
            db=db,
            limit=5,
            user_id=user.id,           # company-wide notes + THIS user's own history, never anyone else's
        )
        from app.services.platform_requests import is_refusal
        memory_context_block = format_memory_block([m for m in memories if not is_refusal(str(m.get("content", "")))])
    except Exception as exc:
        logger.warning("Memory retrieval failed (non-fatal): %s", exc)

    try:
        # Interactive chat runs as a tool-using conversation (the model decides each next step, like ChatGPT/Claude);
        # unattended runs and preset settings changes use the planner.
        use_agent = interactive and preset_plan is None and settings.chat_engine == "agent"
        if has_action_tools or use_agent:
            # ── Planning mode ─────────────────────────────────────────────────
            from app.services.planner import create_and_execute_plan

            rag_text = ""
            if rag_chunks:
                from app.core.engine import _build_rag_context
                rag_text = _build_rag_context(rag_chunks)

            try:
                agent_done = False
                if use_agent:
                    from app.services.chat_agent import run_chat_agent
                    try:
                        # Own savepoint: if the agent breaks unexpectedly, everything it wrote is undone and the
                        # planner answers instead, so a bug or provider quirk never leaves the person with no answer.
                        async with db.begin_nested():
                            final_message, plan_id, all_tool_calls = await run_chat_agent(
                                user_prompt=request.user_prompt,
                                blueprint=augmented_blueprint,
                                session_id=resolved_session_id,
                                db=db,
                                system_persona=augmented_blueprint.system_persona,
                                data_context_block=data_context_block + memory_context_block,
                                rag_context=rag_text,
                            )
                        agent_done = True
                    except Exception:  # noqa: BLE001
                        logger.exception("Chat agent failed unexpectedly; answering with the planner instead")
                if not agent_done:
                    final_message, plan_id, all_tool_calls = await create_and_execute_plan(
                        user_prompt=request.user_prompt,
                        blueprint=augmented_blueprint,
                        session_id=resolved_session_id,
                        db=db,
                        system_persona=augmented_blueprint.system_persona,
                        data_context_block=data_context_block + memory_context_block,
                        rag_context=rag_text,
                        preset_plan=preset_plan,
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

                if plan_status != "failed":   # a failure notice is not an answer worth remembering
                    await _remember(db, authoritative_blueprint.tenant_id, role_key, user.id, request.user_prompt, final_message)
                if plan_status == "completed":
                    await _close_answered_pending_tasks(db, tenant_id, user.id, role_key, request.user_prompt, plan_id)

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
                await _remember(db, authoritative_blueprint.tenant_id, role_key, user.id, request.user_prompt, resp.message)

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


async def _close_answered_pending_tasks(db, tenant_id: str, user_id: str, role_key: str, prompt: str,
                                       plan_id: str | None) -> None:
    """The same request, saved earlier while setup was missing, has now run to completion: it is no longer waiting."""
    from sqlalchemy import select as _select
    from app.db.pending_task_models import PendingTask
    rows = (await db.execute(_select(PendingTask).where(
        PendingTask.tenant_id == tenant_id, PendingTask.user_id == user_id, PendingTask.role_key == role_key,
        PendingTask.prompt == prompt[:4000], PendingTask.status == "waiting_setup"))).scalars().all()
    for t in rows:
        t.status, t.resumed_plan_id = "completed", plan_id
    if rows:
        await db.flush()


# Roles that work with individual people's records. Their conversations must never be written to, or read from, the
# company-wide agent memory (it is shared by every user of the company), or one person's data could surface for another.
PERSONAL_DATA_ROLES = frozenset({"INSTITUTIONAL_CLERK", "MEDICAL_ASSISTANT"})


async def _remember(db, tenant_id: str, role_key: str, user_id: str, prompt: str, answer: str) -> None:
    """Save this exchange as the CALLING USER's own history (never shared). Skipped for roles that handle personal records.
    Runs in its own savepoint so a memory problem can never break or roll back the user's request."""
    if role_key in PERSONAL_DATA_ROLES:
        return
    from app.services.platform_requests import is_refusal
    if is_refusal(answer):
        return                       # a stored "that's not my job" would make the next answer refuse again
    try:
        from app.services.memory_service import store_memory
        async with db.begin_nested():
            await store_memory(tenant_id=tenant_id, role_key=role_key, category="execution_history", title=prompt[:100],
                               content=answer[:500], db=db, confidence=0.8, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory storage failed (non-fatal): %s", exc)


async def _settings_change_plan(prompt: str, tenant_id: str, db) -> tuple[object | None, str]:
    """(plan proposing the exact settings change, '') or (None, question for missing details) or (None, '')."""
    from app.services.admin_customization_service import generate_customization_plan
    from app.services.conversations import turn_history
    from app.services.planner import AgentPlan, PlannedStep
    from app.actions.customize_actions import _describe

    earlier = turn_history.get()
    instruction = (f"{earlier[-1500:]}\n\nThe administrator now asks: {prompt}" if earlier else prompt)[:3000]
    try:
        plan = await generate_customization_plan(instruction, tenant_id, "chat", db)
    except Exception as exc:  # noqa: BLE001 - the normal planner still sees the tool
        logger.warning("Settings-change planning failed, using the normal planner: %s", exc)
        return None, ""
    ops = [op.model_dump() for op in plan.operations]
    if not ops:
        if plan.missing_information:
            return None, ("I can make that change, but I need a little more first:\n"
                          + "\n".join(f"- {m}" for m in plan.missing_information)
                          + "\n\nReply with the details and I will prepare the change for your approval.")
        return None, ""
    args = {"instruction": instruction, "summary": plan.summary, "changes": _describe(ops), "operations": ops,
            "missing_information": plan.missing_information}
    return AgentPlan(objective=prompt[:500], steps=[
        PlannedStep(step_index=0, step_type="action", description=f"Propose: {plan.summary}"[:300],
                    tool_name="customize_eaawp", arguments=args, depends_on=[]),
        PlannedStep(step_index=1, step_type="response", description="Report what was saved", tool_name=None,
                    arguments={}, depends_on=[0]),
    ]), ""


def _turn_history_text() -> str:
    from app.services.conversations import turn_history
    return turn_history.get()


def _blueprint_role_key(role_name: str) -> str:
    mapping = {
        "Digital Marketing Manager": "DIGITAL_MARKETING_MANAGER",
        "Sales Development Rep": "SALES_DEVELOPMENT_REP",
        "Financial Analyst": "FINANCIAL_ANALYST",
        "HR Business Partner": "HR_BUSINESS_PARTNER",
        "Customer Success Manager": "CUSTOMER_SUCCESS_MANAGER",
        "Operations Analyst": "OPERATIONS_ANALYST",
        "Data Intelligence Analyst": "DATA_INTELLIGENCE_ANALYST",
        "Institutional Clerk": "INSTITUTIONAL_CLERK",
        "Medical Assistant": "MEDICAL_ASSISTANT",
    }
    return mapping.get(role_name, "DIGITAL_MARKETING_MANAGER")
