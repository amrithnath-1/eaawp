"""
EAAWP Role Configuration Router

Provides the configuration layer between company/user intent and the
AgentBlueprint that DynamicAgentEngine receives.

Execution flow:
    Company Configuration
        ↓
    Role Configuration  ← this router manages this layer
        ↓
    Validated AgentBlueprint
        ↓
    DynamicAgentEngine → LLM + scoped tools → Execution

Endpoints
---------
GET  /api/v1/roles/{role_key}          — get the role config (auto-seeds defaults)
PUT  /api/v1/roles/{role_key}          — replace the full role config
PATCH /api/v1/roles/{role_key}         — partial update
POST /api/v1/roles/{role_key}/validate — validate without persisting
GET  /api/v1/roles/{role_key}/blueprint — preview the derived AgentBlueprint

All endpoints require X-Tenant-ID header.
Non-implemented role keys return 404 with a clear "coming soon" body.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_tenant_id, require_admin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoleConfiguration
from app.db.session import get_db
from app.schemas.role_config import (
    IMPLEMENTED_ROLES,
    ActiveBlueprintResponse,
    ApprovalRule,
    MemorySettings,
    MonitoringRule,
    RoleComingSoon,
    RoleConfigOut,
    RoleConfigUpdate,
    RoleConfigValidationResult,
    SchedulePreference,
    ToolScopeEntry,
    WorkflowEntry,
)
from app.tools.registry import MASTER_TOOL_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roles", tags=["role-config"])

# ── Default seed values (Digital Marketing Manager) ───────────────────────────
# These are the initial values seeded when the role config doesn't exist yet.
# They mirror DIGITAL_MARKETING_MANAGER_CONFIG from the frontend role-config.ts.

_DMM_DEFAULTS: dict = {
    "role_name": "Digital Marketing Manager",
    "agent_name": "Marketing Intelligence Agent",
    "description": (
        "Monitors campaigns, surfaces content opportunities, and prepares "
        "marketing performance reports."
    ),
    "responsibilities_json": json.dumps([
        "Monitor campaign performance across all channels",
        "Analyse audience engagement metrics",
        "Surface content opportunities and trends",
        "Prepare data-driven marketing reports",
        "Support A/B testing initiatives",
    ]),
    "objectives_json": json.dumps([
        "Improve campaign ROI through continuous performance monitoring",
        "Reduce reporting time by automating data collection",
        "Identify underperforming channels before budget is wasted",
        "Surface actionable insights for the marketing team",
    ]),
    "instructions": (
        "Always cite the data sources behind your insights. "
        "Never send external communications without explicit human approval. "
        "Keep responses concise and data-first."
    ),
    "system_persona": (
        "You are the Marketing Intelligence Agent for this company. "
        "Your role is to support the Digital Marketing Manager by continuously monitoring "
        "campaign performance, analysing audience engagement metrics, surfacing content "
        "opportunities, and preparing data-driven marketing reports. "
        "You have access to campaign analytics, CRM contact data, content scheduling tools, "
        "and the company knowledge base. "
        "You operate under strict data governance: you never send external communications "
        "without explicit human approval, and you always cite the data sources behind your "
        "insights. Your communication style is concise and data-first. "
        "IMPORTANT: Never begin a response with '[AUDIT LOG', '[Action:', 'INT-', or any "
        "internal system reference. Respond naturally and directly to the user."
    ),
    "tool_scopes_json": json.dumps([
        {"name": "Query Campaign Analytics", "tool_key": "query_campaign_analytics",
         "governance": "enabled", "description": "Read-only access to campaign performance metrics"},
        {"name": "Fetch Knowledge Base", "tool_key": "fetch_knowledge_base",
         "governance": "enabled", "description": "Vector search across indexed marketing documents"},
        {"name": "Generate Report", "tool_key": "generate_report",
         "governance": "enabled", "description": "Produce structured marketing performance documents"},
        {"name": "Query Company Data", "tool_key": "query_company_data",
         "governance": "enabled", "description": "Read-only structured access to authorized company database entities via semantic mapping"},
        {"name": "Create Internal Task", "tool_key": "create_internal_task",
         "governance": "enabled", "description": "Create an internal EAAWP task record — low-risk, no external actions"},
        {"name": "Draft Email", "tool_key": "draft_email",
         "governance": "enabled", "description": "Prepare a structured email draft for review — NO external side effect, does not send"},
        {"name": "Send Email", "tool_key": "send_email",
         "governance": "requires_approval", "description": "Send emails — always requires human approval"},
        {"name": "Get Campaigns", "tool_key": "get_campaigns",
         "governance": "enabled", "description": "List internal campaign workspace records — read only"},
        {"name": "Get Campaign Metrics", "tool_key": "get_campaign_metrics",
         "governance": "enabled", "description": "Retrieve campaign performance metrics — read only"},
        {"name": "Get Campaign Summary", "tool_key": "get_campaign_summary",
         "governance": "enabled", "description": "Get campaign summary with KPIs and recent metrics — read only"},
        {"name": "Create Campaign", "tool_key": "create_campaign",
         "governance": "requires_approval", "description": "Create a new internal campaign record — medium risk, requires approval"},
        {"name": "Update Campaign", "tool_key": "update_campaign",
         "governance": "requires_approval", "description": "Update campaign record — high risk for budget/status changes, requires approval"},
        {"name": "Analyse Campaign Performance", "tool_key": "analyze_campaign_performance",
         "governance": "enabled", "description": "Deterministic KPI analysis with period comparison, trends, anomalies — read only"},
        {"name": "Compare Campaigns", "tool_key": "compare_campaigns",
         "governance": "enabled", "description": "Compare multiple campaigns by KPI — read only"},
        {"name": "Get Campaign KPIs", "tool_key": "get_campaign_kpis",
         "governance": "enabled", "description": "Calculate campaign KPIs (CTR, CPC, ROAS, etc.) from recorded metrics — read only"},
        {"name": "Analyse Funnel", "tool_key": "analyze_funnel",
         "governance": "enabled", "description": "Analyse marketing funnel from authorized external company data — read only"},
        {"name": "Get Funnel Metrics", "tool_key": "get_funnel_metrics",
         "governance": "enabled", "description": "Retrieve specific funnel metric values via semantic mapping — read only"},
        {"name": "Analyse Campaign Funnel", "tool_key": "analyze_campaign_funnel",
         "governance": "enabled", "description": "Analyse funnel attributed to a specific campaign — read only"},
        {"name": "Analyse Marketing Strategy", "tool_key": "analyze_marketing_strategy",
         "governance": "enabled", "description": "Evidence-backed strategic analysis combining all intelligence — read only"},
        {"name": "Get Marketing Priorities", "tool_key": "get_marketing_priorities",
         "governance": "enabled", "description": "Get ranked deterministic marketing priorities — read only"},
        {"name": "Get Marketing Objectives", "tool_key": "get_marketing_objectives",
         "governance": "enabled", "description": "List current marketing strategic objectives — read only"},
        {"name": "Create Marketing Objective", "tool_key": "create_marketing_objective",
         "governance": "requires_approval", "description": "Create a strategic marketing objective — medium risk"},
        {"name": "Update Marketing Objective", "tool_key": "update_marketing_objective",
         "governance": "requires_approval", "description": "Update a marketing objective — high risk"},
        {"name": "Generate Content Brief", "tool_key": "generate_content_brief",
         "governance": "enabled", "description": "Generate a marketing content brief using RAG knowledge — low risk"},
        {"name": "Generate Content Ideas", "tool_key": "generate_content_ideas",
         "governance": "enabled", "description": "Generate content ideas for a channel/objective — low risk"},
        {"name": "Generate Content Draft", "tool_key": "generate_content_draft",
         "governance": "enabled", "description": "Generate a marketing content draft — medium risk, no external publish"},
        {"name": "Generate Content Variants", "tool_key": "generate_content_variants",
         "governance": "enabled", "description": "Generate variants of existing content — medium risk, no external publish"},
        {"name": "Analyze Content", "tool_key": "analyze_content",
         "governance": "enabled", "description": "Analyze content quality against objective and audience — low risk"},
    ]),
    "capabilities_json": json.dumps({
        "Campaign analytics": True,
        "Content generation": True,
        "Competitor research": True,
        "Email drafting": True,
        "Report writing": True,
        "Social media scheduling": True,
        "SEO analysis": True,
        "A/B test suggestions": True,
        "Budget tracking": False,
        "Direct ad spend": False,
    }),
    "permissions_json": json.dumps([
        {"action": "Read campaign analytics", "mode": "auto"},
        {"action": "Read knowledge base", "mode": "auto"},
        {"action": "Generate reports", "mode": "auto"},
        {"action": "Send email", "mode": "approval"},
        {"action": "Update CRM records", "mode": "approval"},
        {"action": "Access financial data", "mode": "restricted"},
    ]),
    "workflows_json": json.dumps([
        {"id": "wf-weekly-report", "name": "Weekly Performance Report",
         "description": "Compile and present weekly campaign metrics", "trigger": "scheduled", "enabled": True},
        {"id": "wf-anomaly-detect", "name": "Campaign Anomaly Detection",
         "description": "Alert when a campaign metric deviates significantly", "trigger": "event", "enabled": True},
    ]),
    "monitoring_rules_json": json.dumps([
        {"id": "mr-ctr-drop", "name": "CTR Drop Alert",
         "condition": "CTR drops more than 20% week-over-week", "action": "Flag for review", "enabled": True},
        {"id": "mr-open-rate", "name": "Email Open Rate Watch",
         "condition": "Email open rate below 15%", "action": "Notify manager", "enabled": True},
    ]),
    "communication_style": "Concise",
    "schedule_preferences_json": json.dumps([
        {"task": "Weekly Performance Report", "frequency": "Every Monday 08:00", "enabled": True},
        {"task": "Monthly Summary", "frequency": "1st of month 07:00", "enabled": True},
    ]),
    "memory_settings_json": json.dumps({
        "conversation_window": 10,
        "retain_tool_results": True,
        "summarise_after_turns": 20,
    }),
    "llm_model": "gpt-4o-mini",
    "autonomy_level": 3,
    "quick_prompts_json": json.dumps([
        "Analyse campaign performance this week",
        "What content is trending in our industry?",
        "Prepare monthly marketing report",
        "Which channels are underperforming?",
        "Suggest A/B test ideas for email",
        "Summarise social media engagement",
    ]),
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _orm_to_schema(row: RoleConfiguration) -> RoleConfigOut:
    """Convert a RoleConfiguration ORM row to the output schema."""
    tool_scopes_raw: list[dict] = json.loads(row.tool_scopes_json or "[]")

    allowed_tools = [
        t["tool_key"] for t in tool_scopes_raw
        if t.get("governance") == "enabled"
    ]
    guarded_tools = [
        t["tool_key"] for t in tool_scopes_raw
        if t.get("governance") == "requires_approval"
    ]

    tool_scopes = [ToolScopeEntry(**t) for t in tool_scopes_raw]
    capabilities: dict[str, bool] = json.loads(row.capabilities_json or "{}")
    permissions = [ApprovalRule(**p) for p in json.loads(row.permissions_json or "[]")]
    workflows = [WorkflowEntry(**w) for w in json.loads(row.workflows_json or "[]")]
    monitoring_rules = [MonitoringRule(**m) for m in json.loads(row.monitoring_rules_json or "[]")]
    schedule_prefs = [
        SchedulePreference(**s) for s in json.loads(row.schedule_preferences_json or "[]")
    ]
    memory_raw: dict = json.loads(row.memory_settings_json or "{}")
    memory = MemorySettings(**memory_raw) if memory_raw else MemorySettings()
    quick_prompts: list[str] = json.loads(row.quick_prompts_json or "[]")

    return RoleConfigOut(
        id=row.id,
        tenant_id=row.tenant_id,
        role_key=row.role_key,
        role_name=row.role_name,
        agent_name=row.agent_name,
        description=row.description,
        responsibilities=json.loads(row.responsibilities_json or "[]"),
        objectives=json.loads(row.objectives_json or "[]"),
        instructions=row.instructions,
        system_persona=row.system_persona,
        allowed_tools=allowed_tools,
        guarded_tools=guarded_tools,
        tool_scopes=tool_scopes,
        capabilities=capabilities,
        permissions=permissions,
        workflows=workflows,
        monitoring_rules=monitoring_rules,
        communication_style=row.communication_style,
        schedule_preferences=schedule_prefs,
        memory_settings=memory,
        llm_model=row.llm_model,
        autonomy_level=row.autonomy_level,
        quick_prompts=quick_prompts,
        updated_at=row.updated_at,
    )


async def _get_or_seed(
    role_key: str,
    tenant_id: str,
    db: AsyncSession,
) -> RoleConfiguration:
    """
    Fetch the role config for (tenant_id, role_key).
    If it doesn't exist yet, seed it with the default values and persist.
    """
    import uuid

    result = await db.execute(
        select(RoleConfiguration).where(
            RoleConfiguration.tenant_id == tenant_id,
            RoleConfiguration.role_key == role_key,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    # Seed with defaults based on role_key
    defaults = _get_defaults(role_key)
    row = RoleConfiguration(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        role_key=role_key,
        **defaults,
    )
    db.add(row)
    await db.flush()
    return row


_DATA_ANALYST_DEFAULTS: dict = {
    "role_name": "Data Intelligence Analyst",
    "agent_name": "Data Analyst Agent",
    "description": "Answers questions about the company's uploaded datasets with deterministic, verifiable calculations.",
    "responsibilities_json": json.dumps([
        "Answer business questions from uploaded datasets",
        "Summarise, group, trend and compare data",
        "Explain every figure with its source dataset and filters",
        "Flag data quality problems and limits of the data",
    ]),
    "objectives_json": json.dumps([
        "Give accurate, reproducible numbers",
        "Make data easy to explore without writing queries",
    ]),
    "instructions": (
        "Use list_datasets before analysing. Report only numbers returned by analyze_dataset and always name the "
        "dataset. Do not speculate about causes; say when the data cannot answer the question."
    ),
    "system_persona": (
        "You are the Data Analyst Agent for this company. You answer questions using only the company's uploaded "
        "datasets through the analysis tools. You never invent figures, always cite the dataset, and state the "
        "limits of the data. Be concise and data-first."
    ),
    "tool_scopes_json": json.dumps([
        {"name": "List Datasets", "tool_key": "list_datasets", "governance": "enabled",
         "description": "List uploaded datasets and their columns - read only"},
        {"name": "Analyse Dataset", "tool_key": "analyze_dataset", "governance": "enabled",
         "description": "Answer a question about a dataset with computed figures - read only"},
        {"name": "Fetch Knowledge Base", "tool_key": "fetch_knowledge_base", "governance": "enabled",
         "description": "Search indexed company documents - read only"},
        {"name": "Create Internal Task", "tool_key": "create_internal_task", "governance": "enabled",
         "description": "Create an internal EAAWP task record - low risk"},
        {"name": "Draft Email", "tool_key": "draft_email", "governance": "enabled",
         "description": "Prepare an email draft for review - does not send"},
    ]),
    "capabilities_json": "{}",
    "permissions_json": "[]",
    "workflows_json": "[]",
    "monitoring_rules_json": "[]",
    "communication_style": "Concise",
    "schedule_preferences_json": "[]",
    "memory_settings_json": "{}",
    "llm_model": "gpt-4o-mini",
    "autonomy_level": 3,
    "quick_prompts_json": json.dumps(["What datasets do we have?", "Summarise the main trends in our latest dataset"]),
}


_CLERK_DEFAULTS: dict = {
    "role_name": "Institutional Clerk",
    "agent_name": "Clerk Agent",
    "description": "Handles service requests (certificates, leave, fee queries), prepares draft documents and keeps requesters informed.",
    "responsibilities_json": json.dumps([
        "Triage incoming service requests",
        "Prepare draft certificates, letters and notices from approved templates",
        "Track request status and flag requests that need information",
        "Answer procedural questions from the knowledge base",
    ]),
    "objectives_json": json.dumps([
        "Reduce the time to handle routine requests",
        "Keep every decision traceable and approved by a human",
    ]),
    "instructions": (
        "Use list_service_requests / get_service_request to see requests; you only see what the person asking is allowed to see. "
        "Never issue documents yourself: prepare drafts only. Status changes require human approval. Never invent policy; "
        "search the knowledge base and say when you do not know."
    ),
    "system_persona": (
        "You are the Clerk Agent for this institution. You help with service requests and routine administrative paperwork. "
        "You are precise, courteous and conservative: you draft, a human decides. You never guess personal details and never "
        "disclose another person's request."
    ),
    "tool_scopes_json": json.dumps([
        {"name": "List Service Requests", "tool_key": "list_service_requests", "governance": "enabled",
         "description": "List service requests the asker may see - read only"},
        {"name": "Get Service Request", "tool_key": "get_service_request", "governance": "enabled",
         "description": "Read one service request with its timeline - read only"},
        {"name": "Draft Service Document", "tool_key": "draft_service_document", "governance": "enabled",
         "description": "Prepare a DRAFT document from a template (never issued by the agent)"},
        {"name": "Update Service Request", "tool_key": "update_service_request", "governance": "requires_approval",
         "description": "Change a request's status - always requires human approval"},
        {"name": "Fetch Knowledge Base", "tool_key": "fetch_knowledge_base", "governance": "enabled",
         "description": "Search indexed policies and documents - read only"},
        {"name": "Create Internal Task", "tool_key": "create_internal_task", "governance": "enabled",
         "description": "Create an internal EAAWP task record - low risk"},
    ]),
    "capabilities_json": "{}",
    "permissions_json": "[]",
    "workflows_json": "[]",
    "monitoring_rules_json": "[]",
    "communication_style": "Formal",
    "schedule_preferences_json": "[]",
    "memory_settings_json": "{}",
    "llm_model": "gpt-4o-mini",
    "autonomy_level": 2,
    "quick_prompts_json": json.dumps(["What requests are waiting?", "Draft a bonafide certificate for an approved request"]),
}


def _get_defaults(role_key: str) -> dict:
    """Return seed defaults for the given role key."""
    if role_key == "DIGITAL_MARKETING_MANAGER":
        return _DMM_DEFAULTS
    if role_key == "DATA_INTELLIGENCE_ANALYST":
        return _DATA_ANALYST_DEFAULTS
    if role_key == "INSTITUTIONAL_CLERK":
        return _CLERK_DEFAULTS
    # Fallback minimal defaults for any future role
    return {
        "role_name": role_key.replace("_", " ").title(),
        "agent_name": "AI Agent",
        "description": "",
        "responsibilities_json": "[]",
        "objectives_json": "[]",
        "instructions": "",
        "system_persona": "",
        "tool_scopes_json": "[]",
        "capabilities_json": "{}",
        "permissions_json": "[]",
        "workflows_json": "[]",
        "monitoring_rules_json": "[]",
        "communication_style": "Concise",
        "schedule_preferences_json": "[]",
        "memory_settings_json": "{}",
        "llm_model": "gpt-4o-mini",
        "autonomy_level": 3,
        "quick_prompts_json": "[]",
    }


def _validate_tool_scopes(
    tool_scopes: list[ToolScopeEntry],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """
    Validate tool scopes against MASTER_TOOL_REGISTRY.
    Returns (errors, warnings, allowed_tools, guarded_tools, unrecognised).
    """
    errors: list[str] = []
    warnings: list[str] = []
    allowed: list[str] = []
    guarded: list[str] = []
    unrecognised: list[str] = []

    for scope in tool_scopes:
        if scope.tool_key not in MASTER_TOOL_REGISTRY:
            unrecognised.append(scope.tool_key)
            errors.append(
                f"Tool '{scope.tool_key}' is not in MASTER_TOOL_REGISTRY. "
                f"Available: {sorted(MASTER_TOOL_REGISTRY.keys())}"
            )
        else:
            if scope.governance == "enabled":
                allowed.append(scope.tool_key)
            elif scope.governance == "requires_approval":
                guarded.append(scope.tool_key)

    if not allowed and not guarded:
        warnings.append("No tools are enabled or guarded — the agent will have no tool access.")

    return errors, warnings, allowed, guarded, unrecognised  # type: ignore[return-value]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/{role_key}",
    response_model=RoleConfigOut,
    responses={
        404: {"model": RoleComingSoon, "description": "Role not yet implemented"},
    },
    summary="Get the role configuration for this tenant",
)
async def get_role_config(
    role_key: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleConfigOut:
    if not await _role_available(role_key, tenant_id, db):
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available. Check back in a future release.",
            },
        )
    row = await _get_or_seed(role_key, tenant_id, db)
    return _orm_to_schema(row)


@router.put(
    "/{role_key}",
    response_model=RoleConfigOut,
    summary="Replace the full role configuration",
    dependencies=[Depends(require_admin)],
)
async def replace_role_config(
    role_key: str,
    body: RoleConfigUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleConfigOut:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available. Check back in a future release.",
            },
        )
    row = await _get_or_seed(role_key, tenant_id, db)
    _apply_update(row, body)
    await db.flush()
    return _orm_to_schema(row)


@router.patch(
    "/{role_key}",
    response_model=RoleConfigOut,
    summary="Partially update the role configuration",
    dependencies=[Depends(require_admin)],
)
async def update_role_config(
    role_key: str,
    body: RoleConfigUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleConfigOut:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available. Check back in a future release.",
            },
        )
    row = await _get_or_seed(role_key, tenant_id, db)
    _apply_update(row, body)
    await db.flush()
    return _orm_to_schema(row)


@router.post(
    "/{role_key}/validate",
    response_model=RoleConfigValidationResult,
    summary="Validate a role configuration without persisting it",
)
async def validate_role_config(
    role_key: str,
    body: RoleConfigUpdate,
    tenant_id: str = Depends(get_current_tenant_id),
) -> RoleConfigValidationResult:
    if role_key not in IMPLEMENTED_ROLES:
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available.",
            },
        )

    tool_scopes = body.tool_scopes or []
    errors, warnings, allowed, guarded, unrecognised = _validate_tool_scopes(tool_scopes)

    return RoleConfigValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        allowed_tools=allowed,
        guarded_tools=guarded,
        unrecognised_tools=unrecognised,
    )


@router.get(
    "/{role_key}/blueprint",
    response_model=ActiveBlueprintResponse,
    summary="Preview the AgentBlueprint that would be sent to DynamicAgentEngine",
)
async def get_active_blueprint(
    role_key: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ActiveBlueprintResponse:
    if not await _role_available(role_key, tenant_id, db):
        raise HTTPException(
            status_code=404,
            detail={
                "role_key": role_key,
                "status": "coming_soon",
                "message": "This role is not yet available.",
            },
        )
    row = await _get_or_seed(role_key, tenant_id, db)
    cfg = _orm_to_schema(row)

    return ActiveBlueprintResponse(
        role_key=cfg.role_key,
        agent_id=f"{tenant_id}-{role_key.lower()}",
        role_name=cfg.role_name,
        system_persona=cfg.system_persona,
        allowed_tools=cfg.allowed_tools,
        guarded_tools=cfg.guarded_tools,
        tenant_id=tenant_id,
        llm_model=cfg.llm_model,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

async def _role_available(role_key: str, tenant_id: str, db: AsyncSession) -> bool:
    """Built-in implemented roles, or a role this company created with the AI Employee Builder.

    Reads only: builder-created roles are changed through employee versions (approval + rollback),
    never by writing the role configuration directly.
    """
    if role_key in IMPLEMENTED_ROLES:
        return True
    found = (await db.execute(select(RoleConfiguration.id).where(
        RoleConfiguration.tenant_id == tenant_id, RoleConfiguration.role_key == role_key))).scalar_one_or_none()
    return found is not None


def _apply_update(row: RoleConfiguration, body: RoleConfigUpdate) -> None:
    """Apply non-None fields from body onto the ORM row."""
    if body.role_name is not None:
        row.role_name = body.role_name
    if body.agent_name is not None:
        row.agent_name = body.agent_name
    if body.description is not None:
        row.description = body.description
    if body.responsibilities is not None:
        row.responsibilities_json = json.dumps(body.responsibilities)
    if body.objectives is not None:
        row.objectives_json = json.dumps(body.objectives)
    if body.instructions is not None:
        row.instructions = body.instructions
    if body.tool_scopes is not None:
        row.tool_scopes_json = json.dumps([s.model_dump() for s in body.tool_scopes])
    if body.capabilities is not None:
        row.capabilities_json = json.dumps(body.capabilities)
    if body.permissions is not None:
        row.permissions_json = json.dumps([p.model_dump() for p in body.permissions])
    if body.workflows is not None:
        row.workflows_json = json.dumps([w.model_dump() for w in body.workflows])
    if body.monitoring_rules is not None:
        row.monitoring_rules_json = json.dumps([m.model_dump() for m in body.monitoring_rules])
    if body.communication_style is not None:
        row.communication_style = body.communication_style
    if body.schedule_preferences is not None:
        row.schedule_preferences_json = json.dumps([s.model_dump() for s in body.schedule_preferences])
    if body.memory_settings is not None:
        row.memory_settings_json = json.dumps(body.memory_settings.model_dump())
    if body.llm_model is not None:
        row.llm_model = body.llm_model
    if body.autonomy_level is not None:
        row.autonomy_level = body.autonomy_level
    if body.quick_prompts is not None:
        row.quick_prompts_json = json.dumps(body.quick_prompts)
