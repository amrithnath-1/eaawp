"""
EAAWP Master Tool Registry

MASTER_TOOL_REGISTRY is the single source of truth for every callable tool
in the platform. It maps string keys ? LangChain @tool-decorated functions.

Security contract
-----------------
- No tool may be called unless its key is present in this dictionary.
- The DynamicAgentEngine resolves tool names against this registry ONLY.
- Arbitrary string execution is structurally impossible: resolve_tools()
  raises ValueError for any unrecognised key.

query_company_data
------------------
This tool performs controlled, permission-enforced, read-only queries against
company external databases. It accepts structured parameters � never raw SQL.
It uses a thread-local AsyncSession injected by the execution router so the
tool runs inside the same request transaction context.

Adding a new tool
-----------------
1. Define a @tool-decorated function below.
2. Add its key to MASTER_TOOL_REGISTRY.
3. Add its key to the relevant RoleConfig.toolScopes in role-config.ts (frontend).
"""

from __future__ import annotations

import contextvars
import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# -- Context variable for DB session injection ---------------------------------
# The execution router sets this before invoking the engine so that
# query_company_data can reach the DB session without coupling the tool
# to FastAPI's dependency injection system.
_db_session_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_db_session", default=None
)
_tenant_id_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_tenant_id", default="default-tenant"
)
_role_key_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_role_key", default="DIGITAL_MARKETING_MANAGER"
)
_allowed_tools_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_allowed_tools", default=None
)
_guarded_tools_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_guarded_tools", default=None
)
# -- Phase 3: per-request dynamic tool map -------------------------------------
# Maps tool_key ? LangChain @tool adapter (DynamicToolDefinition wrappers).
# NEVER a process-global singleton � populated fresh per request by the
# execution router and cleared afterwards.  Tenants never share this map.
# Type: dict[str, Any] mapping tool_key ? decorated @tool function.
_dynamic_tools_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "eaawp_dynamic_tools", default=None
)


def set_tool_context(
    db_session,
    tenant_id: str,
    role_key: str,
    allowed_tools: list[str] | None = None,
    guarded_tools: list[str] | None = None,
    dynamic_tools: "dict[str, Any] | None" = None,
) -> None:
    """Called by the execution router before engine.execute() to inject context.

    dynamic_tools: optional mapping of tool_key ? LangChain @tool adapter
                   for the Phase 3 per-request dynamic capability tools.
                   Must be None or a fresh dict built for this tenant/role �
                   never a shared singleton.
    """
    _db_session_ctx.set(db_session)
    _tenant_id_ctx.set(tenant_id)
    _role_key_ctx.set(role_key)
    _allowed_tools_ctx.set(allowed_tools or [])
    _guarded_tools_ctx.set(guarded_tools or [])
    _dynamic_tools_ctx.set(dynamic_tools or {})


def clear_tool_context() -> None:
    """Called by the execution router after engine.execute() completes."""
    _db_session_ctx.set(None)
    _tenant_id_ctx.set("default-tenant")
    _role_key_ctx.set("DIGITAL_MARKETING_MANAGER")
    _allowed_tools_ctx.set(None)
    _guarded_tools_ctx.set(None)
    _dynamic_tools_ctx.set(None)


# -- Starter tools -------------------------------------------------------------


@tool
def fetch_knowledge_base(query: str) -> str:
    """
    Search the company knowledge base using semantic vector search.

    Args:
        query: Natural-language query to search the indexed document store.

    Returns:
        Relevant text chunks from the knowledge base.
    """
    import asyncio
    from app.config import settings as _rag_settings
    _db = _db_session_ctx.get()
    _tid = _tenant_id_ctx.get()
    _rk = _role_key_ctx.get()
    if _db is None:
        return "[ERROR] fetch_knowledge_base: no database session available."
    if not _rag_settings.openai_api_key:
        return "[INFO] Knowledge base search requires OPENAI_API_KEY to be configured."
    try:
        from openai import AsyncOpenAI
        from app.services.vector_store import retrieve_similar_chunks
        _client = AsyncOpenAI(api_key=_rag_settings.openai_api_key)
        _loop = asyncio.get_running_loop()
        _chunks = _loop.run_until_complete(
            retrieve_similar_chunks(
                query=query, tenant_id=_tid, role_scope=_rk,
                db=_db, openai_client=_client, top_k=4,
            )
        )
        if not _chunks:
            return f"No relevant knowledge base entries found for: '{query[:100]}'"
        _lines = [f"Knowledge Base Results for: '{query[:100]}'", ""]
        for _i, _c in enumerate(_chunks, 1):
            _lines.append(f"[{_i}] Source: {_c.document_name} (score:{_c.score:.2f})")
            _lines.append(f"    {_c.text[:400]}")
            _lines.append("")
        return "\n".join(_lines)
    except Exception as _exc:
        logger.error("fetch_knowledge_base error: %s", _exc)
        return f"[ERROR] Knowledge base search failed: {str(_exc)[:200]}"



@tool
def draft_email(email_params: str) -> str:
    """
    Create a structured email draft for review. Has NO external side effect.
    Does NOT send email. Does NOT access SMTP credentials.

    Use this BEFORE send_email to prepare and review an email.
    After creating a draft, the human reviews it and approves send_email separately.

    Args:
        email_params: JSON string with:
            - recipients  (list[str], required): Email addresses (max 10).
            - subject     (str, required): Email subject (max 255 chars).
            - body        (str, required): Email body text.
            - purpose     (str, optional): Why this email is being sent.
            - reply_to    (str, optional): Reply-to email address.
            - evidence_sources (list[str], optional): Data sources used as evidence.

    Returns:
        Draft confirmation with preview. No email is sent.

    Example:
        draft_email('{"recipients": ["manager@company.com"],
                      "subject": "Campaign Alert",
                      "body": "CTR has dropped 25% this week...",
                      "purpose": "Alert on campaign performance decline",
                      "evidence_sources": ["Company data � campaigns"]}')
    """
    import asyncio

    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()

    if db is None:
        return (
            "[ERROR] draft_email tool: no database session available. "
            "This tool requires an active request context."
        )

    try:
        params = json.loads(email_params) if isinstance(email_params, str) else email_params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid email_params JSON: {exc}"

    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        action_request = ActionRequest(
            tool_name="draft_email",
            arguments=params,
            tenant_id=tenant_id,
            role_key=role_key,
            requested_by="agent",
        )

        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or []

        coro = process_action_request(
            request=action_request,
            blueprint_allowed_tools=allowed_tools,
            blueprint_guarded_tools=guarded_tools,
            db=db,
        )

        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)

        if result is None:
            return "[ERROR] draft_email: unexpected None result from action governance."

        return result.message

    except Exception as exc:
        logger.error("draft_email tool error: %s", exc)
        return f"[ERROR] draft_email tool failed: {str(exc)[:200]}"


@tool
def send_email(email_params: str) -> str:
    """
    Send an email on behalf of the Digital Marketing Manager.

    This tool is HIGH risk and ALWAYS requires human approval before sending.
    It routes through the existing action governance pipeline � the email
    will NOT be sent until an administrator explicitly approves the request.

    Args:
        email_params: JSON string with:
            - recipients (list[str], required): Email addresses (max 10).
            - subject    (str, required): Email subject (max 255 chars).
            - body       (str, required): Email body text (max 50,000 chars).
            - reply_to   (str, optional): Reply-to email address.

    Returns:
        Status message. The email is queued for approval, not sent immediately.

    Example:
        send_email('{"recipients": ["user@example.com"], "subject": "Campaign Update",
                    "body": "Here is the weekly campaign summary..."}')
    """
    import asyncio

    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()

    if db is None:
        return (
            "[ERROR] send_email tool: no database session available. "
            "This tool requires an active request context."
        )

    try:
        params = json.loads(email_params) if isinstance(email_params, str) else email_params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid email_params JSON: {exc}"

    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        action_request = ActionRequest(
            tool_name="send_email",
            arguments=params,
            tenant_id=tenant_id,
            role_key=role_key,
            requested_by="agent",
        )

        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or ["send_email"]

        coro = process_action_request(
            request=action_request,
            blueprint_allowed_tools=allowed_tools,
            blueprint_guarded_tools=guarded_tools,
            db=db,
        )

        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)

        if result is None:
            return "[ERROR] send_email: unexpected None result from action governance."

        return result.message

    except Exception as exc:
        logger.error("send_email tool error: %s", exc)
        return f"[ERROR] send_email tool failed: {str(exc)[:200]}"

        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)

        if result is None:
            return "[ERROR] send_email: unexpected None result from action governance."

        return result.message

    except Exception as exc:
        logger.error("send_email tool error: %s", exc)
        return f"[ERROR] send_email tool failed: {str(exc)[:200]}"


@tool
def query_campaign_analytics(channel: str = "all") -> str:
    """
    Query marketing campaign analytics for the Digital Marketing Manager role.

    Args:
        channel: The marketing channel to query
                 (e.g. "email", "social", "paid_search", "all").

    Returns:
        A string summary of campaign performance metrics.
    """
    import asyncio
    _db = _db_session_ctx.get()
    _tid = _tenant_id_ctx.get()
    if _db is None:
        return "[ERROR] query_campaign_analytics: no database session available."
    try:
        from app.services.campaign_service import list_campaigns, get_metrics
        _loop = asyncio.get_running_loop()
        _campaigns = _loop.run_until_complete(
            list_campaigns(tenant_id=_tid, db=_db, status="active", limit=10)
        )
        if not _campaigns:
            return f"No active campaigns found for channel='{channel}'."
        _lines = [f"Campaign Analytics (channel={channel}):"]
        for _c in _campaigns:
            if channel != "all" and _c.channel and channel.lower() not in _c.channel.lower():
                continue
            _lines.append(
                f"  [{_c.status.upper()}] {_c.name} | channel:{_c.channel or 'N/A'} | budget:{_c.budget:,.0f}"
            )
            _metrics = _loop.run_until_complete(
                get_metrics(campaign_id=_c.id, tenant_id=_tid, db=_db, limit=5)
            )
            for _m in _metrics[:3]:
                _lines.append(f"    {_m.metric_date} {_m.metric_name}: {_m.metric_value}")
        if len(_lines) == 1:
            _lines.append(f"  No campaigns found for channel='{channel}'.")
        return "\n".join(_lines)
    except Exception as _exc:
        logger.error("query_campaign_analytics error: %s", _exc)
        return f"[ERROR] query_campaign_analytics: {str(_exc)[:200]}"


@tool
def generate_report(report_type: str, period: str = "current_month") -> str:
    """
    Generate a structured performance report document.

    Args:
        report_type: The type of report (e.g. "marketing_summary", "sales_performance").
        period: The time period covered (e.g. "current_month", "Q3_2026").

    Returns:
        A string confirmation that the report was generated and where it was saved.
    """
    import asyncio
    _db = _db_session_ctx.get()
    _tid = _tenant_id_ctx.get()
    _rk = _role_key_ctx.get()
    if _db is None:
        return "[ERROR] generate_report: no database session available."
    try:
        from app.services.campaign_service import list_campaigns, get_metrics
        _loop = asyncio.get_running_loop()
        _campaigns = _loop.run_until_complete(
            list_campaigns(tenant_id=_tid, db=_db, limit=5)
        )
        _lines = [
            f"=== {report_type.upper()} REPORT ({period}) ===",
            f"Generated for tenant: {_tid[:8]}",
            f"AI Employee role: {_rk}",
            "",
            f"Campaigns summary ({len(_campaigns)} active):",
        ]
        for _c in _campaigns:
            _lines.append(
                f"  - {_c.name} | {_c.channel or 'N/A'} | status:{_c.status} | budget:{_c.budget:,.0f}"
            )
        _lines.extend([
            "",
            "Note: This report was generated from EAAWP internal campaign records.",
            "For external data (Google Analytics, Search Console), ensure integrations are connected.",
        ])
        return "\n".join(_lines)
    except Exception as _exc:
        logger.error("generate_report error: %s", _exc)
        return f"[ERROR] generate_report: {str(_exc)[:200]}"


@tool
def query_company_data(query_params: str) -> str:
    """
    Query authorized company data using structured parameters � NOT raw SQL.

    The tool accepts a JSON string with structured query parameters and
    returns results from the company's connected, permission-controlled database.
    Only entities explicitly authorized by an administrator can be accessed.

    Args:
        query_params: JSON string with the following optional fields:
            - semantic_concept (str): Schema-independent concept (e.g. "campaign_performance")
            - connection_id (str): Direct connection ID (alternative to semantic_concept)
            - entity_id (str): Direct entity ID (alternative to semantic_concept)
            - fields (list[str]): Columns to retrieve. Empty = all allowed columns.
            - filters (list[{field, operator, value}]): WHERE conditions.
              Allowed operators: =, !=, <, <=, >, >=, LIKE, NOT LIKE, IS NULL, IS NOT NULL
            - sort (list[{field, direction}]): ORDER BY. Direction: ASC or DESC.
            - limit (int): Max rows to return (1-200, default 50).

    Returns:
        Formatted string with query results and source metadata.
        If the entity is not authorized, returns an authorization error.
        Never returns database credentials or raw SQL.

    Example:
        query_company_data('{"semantic_concept": "campaign_performance", "limit": 20}')
    """
    import asyncio

    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()

    if db is None:
        return (
            "[ERROR] Company data tool: no database session available. "
            "This tool requires an active request context."
        )

    try:
        from app.schemas.data_access import CompanyDataQueryRequest
        from app.services.data_access import execute_company_data_query

        # Parse structured params
        try:
            params = json.loads(query_params) if isinstance(query_params, str) else query_params
        except json.JSONDecodeError as exc:
            return f"[ERROR] Invalid query_params JSON: {exc}"

        request = CompanyDataQueryRequest(**params)

        # Run async service in the current event loop
        coro = execute_company_data_query(
            request=request,
            tenant_id=tenant_id,
            role_key=role_key,
            db=db,
        )

        # The tool is called from within an already-running async context
        # Use asyncio.ensure_future / get_event_loop().run_until_complete won't work here
        # Instead we use a task in the running loop
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)

        if result is None:
            # Running inside an async context � use nest_asyncio or return a coroutine hint
            # This is handled by the engine calling the tool awaitably
            return "[PENDING] Async execution � results will be returned by the engine."

        # Format results as readable text for the LLM
        if result.row_count == 0:
            return (
                f"Query returned 0 rows from '{result.entity_name}'. "
                f"Source: {', '.join(result.sources)}"
            )

        lines = [
            f"Company Data Query Results",
            f"Entity: {result.entity_name}",
            f"Source: {', '.join(result.sources)}",
            f"Rows returned: {result.row_count}"
            + (" (results truncated at limit)" if result.truncated else ""),
            "",
        ]
        for i, row in enumerate(result.rows[:20], 1):
            row_str = " | ".join(f"{k}: {v}" for k, v in row.items())
            lines.append(f"  {i}. {row_str}")
        if result.row_count > 20:
            lines.append(f"  ... and {result.row_count - 20} more rows")

        return "\n".join(lines)

    except PermissionError as exc:
        return f"[AUTHORIZATION DENIED] {exc}"
    except ValueError as exc:
        return f"[VALIDATION ERROR] {exc}"
    except Exception as exc:
        logger.error("query_company_data tool error: %s", exc)
        return f"[ERROR] Company data query failed: {str(exc)[:200]}"


@tool
def create_internal_task(task_params: str) -> str:
    """
    Create an internal EAAWP task record for tracking purposes.

    This is a LOW-RISK action tool. It only creates an internal task within
    the EAAWP platform � it does NOT send emails, publish content, or call
    any external system.

    Args:
        task_params: JSON string with:
            - title (str, required): Short task title.
            - description (str, optional): Detailed task description.
            - priority (str): "low", "medium", or "high". Default: "medium".
            - department (str): Department. Default: "marketing".

    Returns:
        Confirmation message with the created task ID.
        Awaits human approval before executing if the role requires it.

    Example:
        create_internal_task('{"title": "Review Q4 campaign results", "priority": "high"}')
    """
    import asyncio

    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()

    if db is None:
        return (
            "[ERROR] Action tool: no database session available. "
            "This tool requires an active request context."
        )

    try:
        params = json.loads(task_params) if isinstance(task_params, str) else task_params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid task_params JSON: {exc}"

    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request

        action_request = ActionRequest(
            tool_name="create_internal_task",
            arguments=params,
            tenant_id=tenant_id,
            role_key=role_key,
            requested_by="agent",
        )

        # action tools in the blueprint control allowed/guarded lists
        # Retrieve from context
        allowed_tools = _allowed_tools_ctx.get() or ["create_internal_task"]
        guarded_tools = _guarded_tools_ctx.get() or []

        coro = process_action_request(
            request=action_request,
            blueprint_allowed_tools=allowed_tools,
            blueprint_guarded_tools=guarded_tools,
            db=db,
        )

        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)

        if result is None:
            return "[PENDING] Action tool dispatched � result will be returned by the engine."

        return result.message

    except Exception as exc:
        logger.error("create_internal_task tool error: %s", exc)
        return f"[ERROR] Action tool failed: {str(exc)[:200]}"


# -- Master registry -----------------------------------------------------------



# -- Campaign read tools -------------------------------------------------------

@tool
def get_campaigns(params: str = "{}") -> str:
    """
    List EAAWP-internal marketing campaigns for the tenant.
    LOW risk � read only. No external database access.

    Args:
        params: JSON string. Optional keys: status (str), limit (int, default 20).

    Returns:
        Formatted list of campaigns.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_campaigns: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) and params.strip() else {}
    except json.JSONDecodeError:
        p = {}
    try:
        from app.services.campaign_service import list_campaigns
        coro = list_campaigns(tenant_id=tenant_id, db=db, status=p.get("status"), limit=int(p.get("limit", 20)))
        loop = asyncio.get_running_loop()
        campaigns = loop.run_until_complete(coro)
        if not campaigns:
            return "No campaigns found."
        lines = [f"Campaigns ({len(campaigns)} found):"]
        for c in campaigns:
            lines.append(f"  [{c.status.upper()}] {c.name} (ID:{c.id[:8]}) | {c.channel or 'N/A'} | Budget:{c.budget:,.0f} | {c.start_date or '?'}->{c.end_date or '?'}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_campaigns error: %s", exc)
        return f"[ERROR] get_campaigns: {str(exc)[:200]}"


@tool
def get_campaign_metrics(params: str) -> str:
    """
    Retrieve performance metrics for a campaign.
    LOW risk � read only.

    Args:
        params: JSON string with campaign_id (required), metric_name (optional), limit (optional).

    Returns:
        Formatted metric data.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_campaign_metrics: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    campaign_id = p.get("campaign_id", "")
    if not campaign_id:
        return "[ERROR] campaign_id is required."
    try:
        from app.services.campaign_service import get_metrics
        coro = get_metrics(campaign_id=campaign_id, tenant_id=tenant_id, db=db, metric_name=p.get("metric_name"), limit=int(p.get("limit", 50)))
        loop = asyncio.get_running_loop()
        metrics = loop.run_until_complete(coro)
        if not metrics:
            return f"No metrics found for campaign {campaign_id[:8]}."
        lines = [f"Campaign Metrics ({len(metrics)}):"]
        for m in metrics:
            lines.append(f"  {m.metric_date} | {m.metric_name}: {m.metric_value} [source:{m.source}]")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_campaign_metrics error: %s", exc)
        return f"[ERROR] get_campaign_metrics: {str(exc)[:200]}"


@tool
def get_campaign_summary(campaign_id: str) -> str:
    """
    Get a structured campaign summary with KPIs and recent metrics.
    LOW risk � read only.

    Args:
        campaign_id: The campaign ID to summarise.

    Returns:
        Structured campaign summary.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_campaign_summary: no database session."
    try:
        from app.services.campaign_service import get_campaign_summary as svc_summary
        coro = svc_summary(campaign_id=campaign_id, tenant_id=tenant_id, db=db)
        loop = asyncio.get_running_loop()
        summary = loop.run_until_complete(coro)
        if not summary:
            return f"[ERROR] Campaign {campaign_id[:8]} not found."
        lines = [
            f"Campaign: {summary.name}",
            f"  Status: {summary.status.upper()} | Channel: {summary.channel or 'N/A'}",
            f"  Objective: {summary.objective or 'N/A'}",
            f"  Budget: {summary.budget:,.0f} | Period: {summary.start_date or '?'}->{summary.end_date or '?'}",
            f"  KPIs: {summary.kpi_count} | Metrics: {summary.metric_count}",
        ]
        for m in summary.latest_metrics[:5]:
            lines.append(f"  {m['date']} | {m['name']}: {m['value']} [{m['source']}]")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_campaign_summary error: %s", exc)
        return f"[ERROR] get_campaign_summary: {str(exc)[:200]}"


@tool
def create_campaign_tool(campaign_params: str) -> str:
    """
    Create a new internal marketing campaign. MEDIUM risk � requires approval.
    Does NOT create external ad campaigns.

    Args:
        campaign_params: JSON string with name (required), objective, channel, budget, start_date, end_date.

    Returns:
        Confirmation or approval request ID.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] create_campaign: no database session."
    try:
        params = json.loads(campaign_params) if isinstance(campaign_params, str) else campaign_params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        action_request = ActionRequest(tool_name="create_campaign", arguments=params, tenant_id=tenant_id, role_key=role_key, requested_by="agent")
        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or []
        coro = process_action_request(request=action_request, blueprint_allowed_tools=allowed_tools, blueprint_guarded_tools=guarded_tools, db=db)
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)
        if result is None:
            return "[PENDING] create_campaign dispatched."
        return result.message
    except Exception as exc:
        logger.error("create_campaign tool error: %s", exc)
        return f"[ERROR] create_campaign: {str(exc)[:200]}"


@tool
def update_campaign_tool(campaign_params: str) -> str:
    """
    Update an existing campaign. Budget changes and status transitions require approval.

    Args:
        campaign_params: JSON with campaign_id (required) plus fields to update.

    Returns:
        Confirmation or approval request ID.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] update_campaign: no database session."
    try:
        params = json.loads(campaign_params) if isinstance(campaign_params, str) else campaign_params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        action_request = ActionRequest(tool_name="update_campaign", arguments=params, tenant_id=tenant_id, role_key=role_key, requested_by="agent")
        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or []
        coro = process_action_request(request=action_request, blueprint_allowed_tools=allowed_tools, blueprint_guarded_tools=guarded_tools, db=db)
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)
        if result is None:
            return "[PENDING] update_campaign dispatched."
        return result.message
    except Exception as exc:
        logger.error("update_campaign tool error: %s", exc)
        return f"[ERROR] update_campaign: {str(exc)[:200]}"


@tool
def analyze_campaign_performance_tool(params: str) -> str:
    """
    Analyse campaign performance over a period using deterministic KPI calculations.
    LOW risk � read only. Returns KPIs, period comparison, trends, anomalies, and recommendations.
    All numbers originate from recorded metrics � never fabricated.

    Args:
        params: JSON string with:
            - campaign_id (str, required): Campaign ID to analyse.
            - date_from   (str, optional): Start date YYYY-MM-DD.
            - date_to     (str, optional): End date YYYY-MM-DD.

    Returns:
        Structured performance analysis text with KPIs and evidence-based recommendations.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] analyze_campaign_performance: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    campaign_id = p.get("campaign_id", "")
    if not campaign_id:
        return "[ERROR] campaign_id is required."
    try:
        from app.services.performance_analysis import analyse_campaign_performance, insight_to_dict
        coro = analyse_campaign_performance(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            db=db,
            date_from=p.get("date_from"),
            date_to=p.get("date_to"),
        )
        loop = asyncio.get_running_loop()
        insight = loop.run_until_complete(coro)
        if insight is None:
            return f"[ERROR] Campaign {campaign_id[:8]} not found."
        d = insight_to_dict(insight)
        lines = [
            f"Performance Analysis: {d['campaign_name']}",
            f"Period: {d['period_from'] or 'all'} ? {d['period_to'] or 'all'}",
            f"Data completeness: {d['data_completeness_pct']:.0f}%",
            f"Sources: {', '.join(d['sources'])}",
            "",
            "KPIs:",
        ]
        for name, kpi in d["kpis"].items():
            if kpi["value"] is not None:
                lines.append(f"  {name}: {kpi['value']:.4g}{kpi['unit']}")
            elif kpi["missing_inputs"]:
                lines.append(f"  {name}: N/A (missing: {', '.join(kpi['missing_inputs'])})")
        if d["comparisons"]:
            lines.append("\nPeriod-over-period changes:")
            for c in d["comparisons"]:
                if c["pct_change"] is not None:
                    sig = " [SIGNIFICANT]" if c["is_significant"] else ""
                    anomaly = " [ANOMALY]" if c["is_anomaly"] else ""
                    lines.append(f"  {c['kpi_name']}: {c['pct_change']:+.1f}%{sig}{anomaly}")
        if d["anomalies"]:
            lines.append("\nAnomalies detected:")
            for a in d["anomalies"]:
                lines.append(f"  ? {a}")
        if d["recommendations"]:
            lines.append("\nRecommendations (based on available data):")
            for r in d["recommendations"]:
                lines.append(f"  ? {r}")
        if d["analysis_note"]:
            lines.append(f"\nNote: {d['analysis_note']}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("analyze_campaign_performance error: %s", exc)
        return f"[ERROR] analyze_campaign_performance: {str(exc)[:200]}"


@tool
def compare_campaigns_tool(params: str) -> str:
    """
    Compare multiple campaigns on KPIs over a selected period.
    LOW risk � read only. Returns ranked results only when data is sufficient.

    Args:
        params: JSON string with:
            - campaign_ids (list[str], required): List of campaign IDs to compare.
            - date_from    (str, optional): Start date YYYY-MM-DD.
            - date_to      (str, optional): End date YYYY-MM-DD.
            - rank_by      (str, optional): KPI to rank by. Default: ctr.

    Returns:
        Comparison table with KPI values and ranking.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] compare_campaigns: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    campaign_ids = p.get("campaign_ids", [])
    if not campaign_ids or len(campaign_ids) < 2:
        return "[ERROR] At least 2 campaign_ids required."
    try:
        from app.services.performance_analysis import compare_campaigns
        coro = compare_campaigns(
            campaign_ids=campaign_ids,
            tenant_id=tenant_id,
            db=db,
            date_from=p.get("date_from"),
            date_to=p.get("date_to"),
            rank_by=p.get("rank_by", "ctr"),
        )
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)
        if result is None:
            return "[ERROR] Comparison failed."
        if result.insufficient_data:
            return f"Insufficient data for comparison: {result.insufficient_reason}"
        lines = [f"Campaign Comparison (ranked by {result.ranked_by or 'N/A'}):"]
        for i, cid in enumerate(result.ranking, 1):
            camp = next((c for c in result.campaigns if c["id"] == cid), None)
            if camp:
                kv = " | ".join(
                    f"{k}: {v:.4g}" for k, v in camp["kpi_values"].items()
                    if v is not None and k in result.kpis_compared
                )
                lines.append(f"  #{i} {camp['name']}: {kv or 'No KPI data'}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("compare_campaigns error: %s", exc)
        return f"[ERROR] compare_campaigns: {str(exc)[:200]}"


@tool
def get_campaign_kpis_tool(params: str) -> str:
    """
    Calculate KPIs for a campaign over a period. LOW risk � read only.
    Returns calculated metrics including CTR, CPC, CPM, CPA, ROAS, conversion rate.
    All values are deterministic � never fabricated.

    Args:
        params: JSON string with campaign_id (required), date_from, date_to (optional).

    Returns:
        Calculated KPIs with formulas and missing-data notes.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_campaign_kpis: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    campaign_id = p.get("campaign_id", "")
    if not campaign_id:
        return "[ERROR] campaign_id required."
    try:
        from app.services.campaign_service import get_metrics as svc_get_metrics
        from app.services.kpi_engine import collect_metrics, calculate_all_kpis, data_completeness_pct
        coro = svc_get_metrics(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            db=db,
        )
        loop = asyncio.get_running_loop()
        metric_records = loop.run_until_complete(coro)
        if not metric_records:
            return f"No metrics found for campaign {campaign_id[:8]}."
        records = [{"metric_name": m.metric_name, "metric_value": m.metric_value, "metric_date": m.metric_date} for m in metric_records]
        aggregated = collect_metrics(records, p.get("date_from"), p.get("date_to"))
        kpis = calculate_all_kpis(aggregated)
        completeness = data_completeness_pct(aggregated)
        lines = [f"KPIs for campaign {campaign_id[:8]} (completeness: {completeness:.0f}%):"]
        for name, kpi in kpis.items():
            if kpi.value is not None:
                lines.append(f"  {name}: {kpi.value:.4g}{kpi.unit}  [{kpi.formula}]")
            elif kpi.missing_inputs:
                lines.append(f"  {name}: N/A (missing: {', '.join(kpi.missing_inputs)})")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_campaign_kpis error: %s", exc)
        return f"[ERROR] get_campaign_kpis: {str(exc)[:200]}"


@tool
def analyze_funnel_tool(params: str) -> str:
    """
    Analyse the marketing funnel from authorized external company data.
    LOW risk � read only. Uses existing semantic mapping layer.
    Never executes arbitrary SQL or accesses credentials.

    Args:
        params: JSON with:
            - concepts (list[str], optional): Funnel concepts to retrieve.
              Defaults to all standard funnel concepts.
            - period (str, optional): Period label for display.

    Returns:
        Funnel analysis with conversion rates, findings, and recommendations.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] analyze_funnel: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) and params.strip() else {}
    except json.JSONDecodeError:
        p = {}
    from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
    concepts = p.get("concepts") or list(FUNNEL_SEMANTIC_CONCEPTS)
    period = p.get("period", "")
    try:
        from app.services.funnel_service import fetch_funnel_from_external, calculate_funnel, funnel_to_dict
        coro = fetch_funnel_from_external(tenant_id=tenant_id, role_key=role_key, concepts=concepts, db=db)
        loop = asyncio.get_running_loop()
        ext = loop.run_until_complete(coro)
        # Map external concept names to funnel stage names
        concept_to_stage = {
            "visitor_count": "visitors", "lead_count": "leads",
            "qualified_lead_count": "qualified_leads", "opportunity_count": "opportunities",
            "customer_count": "customers", "conversion_count": "customers",
        }
        stage_vals = {concept_to_stage.get(k, k): v for k, v in ext.items() if k in concept_to_stage}
        spend = ext.get("campaign_spend")
        revenue = ext.get("revenue")
        funnel = calculate_funnel(stage_vals, spend=spend, revenue=revenue, period=period,
                                  sources=[f"External: {c}" for c in concepts if ext.get(c) is not None])
        d = funnel_to_dict(funnel)
        lines = [f"Funnel Analysis (completeness: {d['data_completeness_pct']:.0f}%):"]
        for s in d["stages"]:
            if s["value"] is not None:
                lines.append(f"  {s['name']}: {s['value']:.0f}")
            else:
                lines.append(f"  {s['name']}: N/A ({s['missing_reason']})")
        for cr in d["conversion_rates"]:
            if cr["rate_pct"] is not None:
                lines.append(f"  {cr['from_stage']}?{cr['to_stage']}: {cr['rate_pct']:.2f}%")
        if d["findings"]:
            lines.append("Findings:")
            for f in d["findings"]:
                lines.append(f"  � {f}")
        if d["recommendations"]:
            lines.append("Recommendations:")
            for r in d["recommendations"]:
                lines.append(f"  ? {r}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("analyze_funnel error: %s", exc)
        return f"[ERROR] analyze_funnel: {str(exc)[:200]}"


@tool
def get_funnel_metrics_tool(params: str = "{}") -> str:
    """
    Get specific funnel metric values from authorized external company data.
    LOW risk � read only. Concepts must have valid semantic mappings.

    Args:
        params: JSON with:
            - concepts (list[str]): Funnel concepts to retrieve.

    Returns:
        Available metric values with source metadata.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] get_funnel_metrics: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) and params.strip() else {}
    except json.JSONDecodeError:
        p = {}
    from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS
    concepts = p.get("concepts") or list(FUNNEL_SEMANTIC_CONCEPTS)
    # Validate against allowed concepts
    invalid = [c for c in concepts if c not in FUNNEL_SEMANTIC_CONCEPTS]
    if invalid:
        return f"[ERROR] Unknown funnel concepts: {invalid}. Allowed: {sorted(FUNNEL_SEMANTIC_CONCEPTS)}"
    try:
        from app.services.funnel_service import fetch_funnel_from_external
        coro = fetch_funnel_from_external(tenant_id=tenant_id, role_key=role_key, concepts=concepts, db=db)
        loop = asyncio.get_running_loop()
        results = loop.run_until_complete(coro)
        lines = ["Funnel Metrics:"]
        for c, v in results.items():
            if v is not None:
                lines.append(f"  {c}: {v:.0f}")
            else:
                lines.append(f"  {c}: N/A (no mapping or not accessible)")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_funnel_metrics error: %s", exc)
        return f"[ERROR] get_funnel_metrics: {str(exc)[:200]}"


@tool
def analyze_campaign_funnel_tool(params: str) -> str:
    """
    Analyse the funnel attributed to a specific campaign.
    LOW risk � read only. Uses campaign metrics and semantic mapping.

    Args:
        params: JSON with:
            - campaign_id (str, required): EAAWP campaign ID.
            - date_from, date_to (str, optional): Period dates.
            - external_concepts (list[str], optional): External concepts to supplement.

    Returns:
        Campaign funnel analysis with conversion rates and efficiency metrics.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] analyze_campaign_funnel: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    campaign_id = p.get("campaign_id", "")
    if not campaign_id:
        return "[ERROR] campaign_id is required."
    try:
        from app.services.campaign_service import get_metrics as svc_metrics
        from app.services.kpi_engine import collect_metrics, normalise_metric_name
        from app.services.funnel_service import (
            fetch_funnel_from_external, calculate_funnel, funnel_to_dict
        )
        from app.schemas.funnel import FUNNEL_SEMANTIC_CONCEPTS

        # Get internal campaign metrics
        coro = svc_metrics(campaign_id=campaign_id, tenant_id=tenant_id, db=db)
        loop = asyncio.get_running_loop()
        metrics = loop.run_until_complete(coro)
        records = [{"metric_name": m.metric_name, "metric_value": m.metric_value, "metric_date": m.metric_date} for m in metrics]
        internal = collect_metrics(records, p.get("date_from"), p.get("date_to"))

        # Map campaign metrics to funnel stages
        stage_vals: dict[str, float | None] = {}
        for k, v in internal.items():
            nk = normalise_metric_name(k)
            if nk in ("leads", "visitors", "conversions", "customers"):
                stage_vals[nk] = v
            elif nk == "conversion":
                stage_vals["customers"] = stage_vals.get("customers", 0.0) + v

        # Optionally fetch external concepts
        ext_concepts = p.get("external_concepts", [])
        ext_vals: dict[str, float | None] = {}
        if ext_concepts:
            valid = [c for c in ext_concepts if c in FUNNEL_SEMANTIC_CONCEPTS]
            if valid:
                coro2 = fetch_funnel_from_external(tenant_id=tenant_id, role_key=role_key, concepts=valid, db=db)
                ext_vals = loop.run_until_complete(coro2)

        concept_to_stage = {
            "visitor_count": "visitors", "lead_count": "leads",
            "qualified_lead_count": "qualified_leads", "opportunity_count": "opportunities",
            "customer_count": "customers",
        }
        for k, v in ext_vals.items():
            stage = concept_to_stage.get(k)
            if stage and v is not None and stage not in stage_vals:
                stage_vals[stage] = v

        spend = internal.get("spend") or ext_vals.get("campaign_spend")
        revenue = internal.get("revenue") or ext_vals.get("revenue")

        sources = [f"EAAWP campaign metrics ({len(records)} records)"]
        if ext_vals:
            sources.append(f"External concepts: {[k for k,v in ext_vals.items() if v is not None]}")

        funnel = calculate_funnel(stage_vals, spend=spend, revenue=revenue,
                                  period=f"{p.get('date_from','')}�{p.get('date_to','')}", sources=sources)
        d = funnel_to_dict(funnel)
        lines = [f"Campaign Funnel: {campaign_id[:8]} (completeness: {d['data_completeness_pct']:.0f}%)"]
        for s in d["stages"]:
            if s["value"] is not None:
                lines.append(f"  {s['name']}: {s['value']:.0f}")
        for cr in d["conversion_rates"]:
            if cr["rate_pct"] is not None:
                lines.append(f"  {cr['from_stage']}?{cr['to_stage']}: {cr['rate_pct']:.2f}%")
        eff = [f"CPL={d['cost_per_lead']:.2f}" if d["cost_per_lead"] else "",
               f"CAC={d['cost_per_customer']:.2f}" if d["cost_per_customer"] else "",
               f"ROAS={d['roas']:.2f}x" if d["roas"] else ""]
        eff = [e for e in eff if e]
        if eff:
            lines.append("  " + " | ".join(eff))
        if d["findings"]:
            lines.append("Findings:")
            for f in d["findings"]:
                lines.append(f"  � {f}")
        if d["recommendations"]:
            lines.append("Recommendations:")
            for r in d["recommendations"]:
                lines.append(f"  ? {r}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("analyze_campaign_funnel error: %s", exc)
        return f"[ERROR] analyze_campaign_funnel: {str(exc)[:200]}"


@tool
def analyze_marketing_strategy_tool(params: str = "{}") -> str:
    """
    Combine campaign performance, funnel intelligence, and monitoring findings
    into a structured strategic analysis.
    LOW risk � read only. All numbers are deterministic � never LLM-fabricated.

    Args:
        params: JSON with optional campaign_insights (list), funnel_insights (list),
                monitoring_anomalies (list[str]).

    Returns:
        Structured strategic analysis with priorities, evidence, and recommended actions.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] analyze_marketing_strategy: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) and params.strip() else {}
    except json.JSONDecodeError:
        p = {}
    try:
        from app.services.strategy_service import build_strategic_analysis, analysis_to_dict
        coro = build_strategic_analysis(
            tenant_id=tenant_id, db=db,
            campaign_insights=p.get("campaign_insights"),
            funnel_insights=p.get("funnel_insights"),
            monitoring_anomalies=p.get("monitoring_anomalies"),
        )
        loop = asyncio.get_running_loop()
        analysis = loop.run_until_complete(coro)
        if analysis is None:
            return "[PENDING] analyze_marketing_strategy dispatched."
        d = analysis_to_dict(analysis)
        lines = [
            f"Strategic Analysis ({d['generated_at'][:10]})",
            f"Situation: {d['current_situation']}",
            f"Data completeness: {d['data_completeness_pct']:.0f}%",
        ]
        if d["top_problems"]:
            lines.append("\nTop Problems:")
            for p in d["top_problems"][:3]:
                lines.append(f"  [{p['severity'].upper()}] {p['title']} (score:{p['priority_score']:.0f})")
                lines.append(f"    Evidence: {'; '.join(p['evidence'][:2])}")
        if d["top_opportunities"]:
            lines.append("\nTop Opportunities:")
            for o in d["top_opportunities"][:3]:
                lines.append(f"  [{o['severity'].upper()}] {o['title']} (score:{o['priority_score']:.0f})")
        if d["recommended_actions"]:
            lines.append("\nRecommended Actions (require governance to execute):")
            for a in d["recommended_actions"][:4]:
                lines.append(f"  ? {a}")
        if d["uncertainties"]:
            lines.append("\nUncertainties:")
            for u in d["uncertainties"][:3]:
                lines.append(f"  ? {u}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("analyze_marketing_strategy error: %s", exc)
        return f"[ERROR] analyze_marketing_strategy: {str(exc)[:200]}"


@tool
def get_marketing_priorities_tool(params: str = "{}") -> str:
    """
    Get the current deterministic marketing priorities from available intelligence.
    LOW risk � read only.

    Args:
        params: JSON with optional campaign_insights (list) and funnel_insights (list).

    Returns:
        Ranked priority list with scores, evidence, and approval requirements.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_marketing_priorities: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) and params.strip() else {}
    except json.JSONDecodeError:
        p = {}
    try:
        from app.services.strategy_service import build_strategic_analysis, analysis_to_dict
        coro = build_strategic_analysis(
            tenant_id=tenant_id, db=db,
            campaign_insights=p.get("campaign_insights"),
            funnel_insights=p.get("funnel_insights"),
        )
        loop = asyncio.get_running_loop()
        analysis = loop.run_until_complete(coro)
        if analysis is None:
            return "[PENDING] get_marketing_priorities dispatched."
        d = analysis_to_dict(analysis)
        lines = [f"Marketing Priorities ({len(d['all_priorities'])} total):"]
        for i, pr in enumerate(d["all_priorities"][:8], 1):
            lines.append(
                f"  {i}. [{pr['severity'].upper()}] {pr['title']}\n"
                f"     Score: {pr['priority_score']:.0f} | Approval: {pr['required_approval']}\n"
                f"     Next step: {pr['recommended_next_step'][:100]}"
            )
        if not d["all_priorities"]:
            lines.append("  No significant priorities detected with current data.")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_marketing_priorities error: %s", exc)
        return f"[ERROR] get_marketing_priorities: {str(exc)[:200]}"


@tool
def get_marketing_objectives_tool(status: str = "") -> str:
    """
    Get current marketing objectives for the tenant.
    LOW risk � read only.

    Args:
        status: Optional filter (draft/active/achieved/paused/cancelled).

    Returns:
        List of marketing objectives with current vs target values.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] get_marketing_objectives: no database session."
    try:
        from app.services.strategy_service import list_objectives
        coro = list_objectives(tenant_id=tenant_id, db=db, status=status or None)
        loop = asyncio.get_running_loop()
        objectives = loop.run_until_complete(coro)
        if not objectives:
            return "No marketing objectives found."
        lines = [f"Marketing Objectives ({len(objectives)}):"]
        for o in objectives:
            progress = ""
            if o.target_value and o.current_value:
                pct = (o.current_value / o.target_value * 100)
                progress = f" [{pct:.0f}% of target]"
            lines.append(
                f"  [{o.priority}? {o.status.upper()}] {o.name} ({o.objective_type})"
                f" � {o.target_metric}{progress}"
            )
        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_marketing_objectives error: %s", exc)
        return f"[ERROR] get_marketing_objectives: {str(exc)[:200]}"


@tool
def create_marketing_objective_tool(params: str) -> str:
    """
    Create a marketing strategic objective. MEDIUM risk � requires approval.

    Args:
        params: JSON with name (required), objective_type, priority (1-5),
                target_metric, target_value.

    Returns:
        Confirmation or approval request ID.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] create_marketing_objective: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        action_request = ActionRequest(
            tool_name="create_marketing_objective", arguments=p,
            tenant_id=tenant_id, role_key=role_key, requested_by="agent",
        )
        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or []
        coro = process_action_request(
            request=action_request, blueprint_allowed_tools=allowed_tools,
            blueprint_guarded_tools=guarded_tools, db=db,
        )
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)
        if result is None:
            return "[PENDING] create_marketing_objective dispatched."
        return result.message
    except Exception as exc:
        logger.error("create_marketing_objective tool error: %s", exc)
        return f"[ERROR] create_marketing_objective: {str(exc)[:200]}"


@tool
def update_marketing_objective_tool(params: str) -> str:
    """
    Update a marketing objective. HIGH risk � requires approval.

    Args:
        params: JSON with objective_id (required), and optional name, priority,
                status, target_value, current_value.

    Returns:
        Confirmation or approval request ID.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    role_key = _role_key_ctx.get()
    if db is None:
        return "[ERROR] update_marketing_objective: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    try:
        from app.schemas.actions import ActionRequest
        from app.services.action_governance import process_action_request
        action_request = ActionRequest(
            tool_name="update_marketing_objective", arguments=p,
            tenant_id=tenant_id, role_key=role_key, requested_by="agent",
        )
        allowed_tools = _allowed_tools_ctx.get() or []
        guarded_tools = _guarded_tools_ctx.get() or []
        coro = process_action_request(
            request=action_request, blueprint_allowed_tools=allowed_tools,
            blueprint_guarded_tools=guarded_tools, db=db,
        )
        loop = asyncio.get_running_loop()
        result = loop.run_until_complete(coro)
        if result is None:
            return "[PENDING] update_marketing_objective dispatched."
        return result.message
    except Exception as exc:
        logger.error("update_marketing_objective tool error: %s", exc)
        return f"[ERROR] update_marketing_objective: {str(exc)[:200]}"


@tool
def generate_content_brief_tool(params: str) -> str:
    """
    Generate a structured marketing content brief using company knowledge.
    LOW risk � read/generation only. Uses existing RAG system for brand context.

    Args:
        params: JSON with objective (required), target_audience, channel,
                campaign_name, tone, additional_context.

    Returns:
        Generated brief saved as a content item.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] generate_content_brief: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    if not p.get("objective"):
        return "[ERROR] 'objective' is required."
    try:
        from app.schemas.content import GenerateBriefRequest
        from app.services.content_service import generate_brief
        req = GenerateBriefRequest(**{k: v for k, v in p.items() if k in GenerateBriefRequest.model_fields})
        loop = asyncio.get_running_loop()
        item = loop.run_until_complete(generate_brief(req, tenant_id, db))
        if item is None:
            return "[PENDING] generate_content_brief dispatched."
        sources = f" (sources: {', '.join(item.rag_sources[:3])})" if item.rag_sources else ""
        return f"Content brief created (ID: {item.id[:8]}).\nTitle: {item.title}\n\n{item.body[:600]}...{sources}"
    except Exception as exc:
        logger.error("generate_content_brief error: %s", exc)
        return f"[ERROR] generate_content_brief: {str(exc)[:200]}"


@tool
def generate_content_ideas_tool(params: str) -> str:
    """
    Generate marketing content ideas for a given objective and channel.
    LOW risk � generation only. Uses RAG for brand context.

    Args:
        params: JSON with objective (required), channel, target_audience, n_ideas (1-10).

    Returns:
        Generated ideas saved as a content item.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] generate_content_ideas: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    if not p.get("objective"):
        return "[ERROR] 'objective' is required."
    try:
        from app.schemas.content import GenerateIdeasRequest
        from app.services.content_service import generate_ideas
        req = GenerateIdeasRequest(**{k: v for k, v in p.items() if k in GenerateIdeasRequest.model_fields})
        loop = asyncio.get_running_loop()
        item = loop.run_until_complete(generate_ideas(req, tenant_id, db))
        if item is None:
            return "[PENDING] generate_content_ideas dispatched."
        return f"Content ideas created (ID: {item.id[:8]}).\n\n{item.body[:800]}"
    except Exception as exc:
        logger.error("generate_content_ideas error: %s", exc)
        return f"[ERROR] generate_content_ideas: {str(exc)[:200]}"


@tool
def generate_content_draft_tool(params: str) -> str:
    """
    Generate a marketing content draft for the specified channel.
    MEDIUM risk � uses LLM and RAG. Does NOT publish externally.

    Args:
        params: JSON with objective (required), channel, target_audience,
                tone, cta, max_words, campaign_id.

    Returns:
        Generated draft saved as a content item.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] generate_content_draft: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    if not p.get("objective"):
        return "[ERROR] 'objective' is required."
    try:
        from app.schemas.content import GenerateDraftRequest
        from app.services.content_service import generate_draft
        req = GenerateDraftRequest(**{k: v for k, v in p.items() if k in GenerateDraftRequest.model_fields})
        loop = asyncio.get_running_loop()
        item = loop.run_until_complete(generate_draft(req, tenant_id, db))
        if item is None:
            return "[PENDING] generate_content_draft dispatched."
        sources = f"\nSources: {', '.join(item.rag_sources[:3])}" if item.rag_sources else ""
        return f"Content draft created (ID: {item.id[:8]}).\nTitle: {item.title}\nChannel: {item.channel}\n\n{item.body[:800]}{sources}"
    except Exception as exc:
        logger.error("generate_content_draft error: %s", exc)
        return f"[ERROR] generate_content_draft: {str(exc)[:200]}"


@tool
def generate_content_variants_tool(params: str) -> str:
    """
    Generate multiple variants of an existing content item.
    MEDIUM risk � generation only. Does NOT publish externally.

    Args:
        params: JSON with source_content_id (required), n_variants (1-5),
                variation_instructions.

    Returns:
        Generated variants as content items.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] generate_content_variants: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    if not p.get("source_content_id"):
        return "[ERROR] 'source_content_id' is required."
    try:
        from app.schemas.content import GenerateVariantsRequest
        from app.services.content_service import generate_variants
        req = GenerateVariantsRequest(**{k: v for k, v in p.items() if k in GenerateVariantsRequest.model_fields})
        loop = asyncio.get_running_loop()
        variants = loop.run_until_complete(generate_variants(req, tenant_id, db))
        if not variants:
            return "[PENDING] generate_content_variants dispatched."
        lines = [f"Created {len(variants)} content variant(s):"]
        for v in variants:
            lines.append(f"  Variant {v.id[:8]}: {v.title}")
        return "\n".join(lines)
    except ValueError as exc:
        return f"[ERROR] {exc}"
    except Exception as exc:
        logger.error("generate_content_variants error: %s", exc)
        return f"[ERROR] generate_content_variants: {str(exc)[:200]}"


@tool
def analyze_content_tool(params: str) -> str:
    """
    Analyse existing content against campaign objective, audience, and CTA.
    LOW risk � read/analysis only. Uses RAG for brand guidelines context.

    Args:
        params: JSON with content_id (required), campaign_objective,
                target_audience, cta, channel.

    Returns:
        Analysis with scores, strengths, improvement areas, and recommendations.
    """
    import asyncio
    db = _db_session_ctx.get()
    tenant_id = _tenant_id_ctx.get()
    if db is None:
        return "[ERROR] analyze_content: no database session."
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return f"[ERROR] Invalid JSON: {exc}"
    if not p.get("content_id"):
        return "[ERROR] 'content_id' is required."
    try:
        from app.schemas.content import AnalyzeContentRequest
        from app.services.content_service import analyze_content
        req = AnalyzeContentRequest(**{k: v for k, v in p.items() if k in AnalyzeContentRequest.model_fields})
        loop = asyncio.get_running_loop()
        item = loop.run_until_complete(analyze_content(req, tenant_id, db))
        if item is None:
            return "[PENDING] analyze_content dispatched."
        analysis_text = item.analysis.get("analysis", "Analysis not available.")
        sources = f"\nSources: {', '.join(item.rag_sources[:3])}" if item.rag_sources else ""
        return f"Content Analysis (ID: {item.id[:8]}):\n\n{analysis_text[:800]}{sources}"
    except ValueError as exc:
        return f"[ERROR] {exc}"
    except Exception as exc:
        logger.error("analyze_content error: %s", exc)
        return f"[ERROR] analyze_content: {str(exc)[:200]}"


MASTER_TOOL_REGISTRY: dict[str, object] = {
    "fetch_knowledge_base": fetch_knowledge_base,
    "draft_email": draft_email,
    "send_email": send_email,
    "query_campaign_analytics": query_campaign_analytics,
    "generate_report": generate_report,
    "query_company_data": query_company_data,
    "create_internal_task": create_internal_task,
    "get_campaigns": get_campaigns,
    "get_campaign_metrics": get_campaign_metrics,
    "get_campaign_summary": get_campaign_summary,
    "create_campaign": create_campaign_tool,
    "update_campaign": update_campaign_tool,
    "analyze_campaign_performance": analyze_campaign_performance_tool,
    "compare_campaigns": compare_campaigns_tool,
    "get_campaign_kpis": get_campaign_kpis_tool,
    "analyze_funnel": analyze_funnel_tool,
    "get_funnel_metrics": get_funnel_metrics_tool,
    "analyze_campaign_funnel": analyze_campaign_funnel_tool,
    "analyze_marketing_strategy": analyze_marketing_strategy_tool,
    "get_marketing_priorities": get_marketing_priorities_tool,
    "get_marketing_objectives": get_marketing_objectives_tool,
    "create_marketing_objective": create_marketing_objective_tool,
    "update_marketing_objective": update_marketing_objective_tool,
    "generate_content_brief": generate_content_brief_tool,
    "generate_content_ideas": generate_content_ideas_tool,
    "generate_content_draft": generate_content_draft_tool,
    "generate_content_variants": generate_content_variants_tool,
    "analyze_content": analyze_content_tool,
}


def resolve_tools(
    tool_names: list[str],
    dynamic_tool_map: "dict[str, Any] | None" = None,
) -> list[object]:
    """
    Resolve a list of tool name strings to their @tool-decorated callables.

    Checks MASTER_TOOL_REGISTRY first (static tools always take precedence).
    Falls back to dynamic_tool_map for Phase 3 integration-backed tools.

    Args:
        tool_names:       List of tool key strings from the blueprint.
        dynamic_tool_map: Optional per-request map of dynamic tool adapters.
                          Must be tenant-scoped � never the global registry.

    Raises:
        ValueError: If any name is not found in either registry.
    """
    resolved = []
    dynamic = dynamic_tool_map or {}
    for name in tool_names:
        if name in MASTER_TOOL_REGISTRY:
            resolved.append(MASTER_TOOL_REGISTRY[name])
        elif name in dynamic:
            resolved.append(dynamic[name])
        else:
            raise ValueError(
                f"Tool '{name}' is not registered in MASTER_TOOL_REGISTRY "
                f"or the current dynamic tool map. "
                f"Registered static tools: {sorted(MASTER_TOOL_REGISTRY.keys())}"
            )
    return resolved



