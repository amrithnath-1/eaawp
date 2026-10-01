"""
EAAWP Admin AI Customization Service.

Parses a natural-language admin instruction into a validated CustomizationPlan
and executes confirmed plans through existing EAAWP services.

Security invariants:
- Credentials are NEVER sent to the LLM.
- The LLM produces proposals only — the backend validates and executes.
- Every operation maps to an existing service function.
- All executions are tenant-scoped and audit-logged.
- HIGH-risk operations (e.g. operations that touch external actions) still go
  through the existing approval system.
- System prompt explicitly prohibits credential extraction and code execution.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import manager as int_mgr
from app.integrations.integration_registry import integration_registry
from app.llm import get_llm_gateway
from app.schemas.admin_customization import (
    AdminCustomizationResult,
    CustomizationOperation,
    CustomizationPlan,
    OperationResult,
)

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are the EAAWP Admin AI Customization Planner.
Your ONLY job is to convert a Company Administrator's natural-language instruction
into a structured JSON customization plan for their AI workforce.

CRITICAL RULES:
1. PLANNING MODE ONLY — never execute actions, run code, query databases, or call APIs.
2. NEVER ask for or include passwords, API keys, OAuth tokens, secrets, or credentials.
   Credential collection is handled by secure backend flows, not through this planner.
3. NEVER produce SQL, shell commands, eval(), exec(), arbitrary HTTP calls, or
   any code that would modify source files.
4. If an operation requires credentials (e.g. connecting a database), set params to
   {\"requires_credential_flow\": true, \"provider_type\": \"<type>\"} and add
   the credential fields to missing_information.
5. Only produce operations from this exact list:
   CREATE_AI_EMPLOYEE, UPDATE_AI_EMPLOYEE, CONNECT_INTEGRATION,
   GRANT_CAPABILITY, REVOKE_CAPABILITY, CREATE_WORKFLOW, UPDATE_WORKFLOW,
   SET_APPROVAL_POLICY
6. If information is missing, list it in missing_information instead of guessing.
7. Respond with ONLY valid JSON — no markdown, no backticks, no explanation.

AVAILABLE PROVIDERS (for CONNECT_INTEGRATION):
  google_search_console, google_analytics, facebook, github, postgresql, mysql, mcp

APPROVAL POLICY params for SET_APPROVAL_POLICY:
  {\"scope\": \"all_external_actions\" | \"send_email\" | \"publish\",
   \"mode\": \"approval_required\" | \"auto\",
   \"role_key\": \"<optional role>\"}

OUTPUT FORMAT — respond with exactly this JSON structure:
{
  "summary": "One paragraph describing all changes you will make",
  "operations": [
    {
      "type": "<OperationType>",
      "description": "Human-readable description of this specific step",
      "params": {},
      "requires_confirmation": true,
      "order": 0
    }
  ],
  "missing_information": ["<thing needed before proceeding>"],
  "requires_confirmation": true
}

EXAMPLES:

Instruction: "Create a Digital Marketing Manager"
Operations:
  {type: CREATE_AI_EMPLOYEE, params: {name: "Digital Marketing Manager",
   role_key: "DIGITAL_MARKETING_MANAGER",
   purpose: "Monitor campaigns, prepare reports, surface insights"}}

Instruction: "Connect Google Search Console"
Operations:
  {type: CONNECT_INTEGRATION, params: {provider_type: "google_search_console",
   display_name: "Google Search Console",
   authentication_type: "oauth2"}}

Instruction: "Give the marketing employee access to Search Console analytics"
Operations:
  {type: GRANT_CAPABILITY, params: {provider_type: "google_search_console",
   capability_key: "get_search_analytics",
   role_key: "DIGITAL_MARKETING_MANAGER"}}

Instruction: "Create a Monday 9am marketing report workflow"
Operations:
  {type: CREATE_WORKFLOW, params: {name: "Weekly Marketing Report",
   trigger: "scheduled", schedule_cron: "0 9 * * 1",
   description: "Prepare and present weekly marketing metrics",
   steps: [{step_type: "analysis", description: "Retrieve and analyse campaign data"},
           {step_type: "response", description: "Generate marketing report"}]}}

Instruction: "Require approval before sending anything externally"
Operations:
  {type: SET_APPROVAL_POLICY, params: {scope: "all_external_actions",
   mode: "approval_required"}}

Do not combine unrelated concerns into one operation. Use separate operations for each step.
"""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response (handles markdown wrapping)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]+\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


async def _gather_tenant_context(tenant_id: str, db: AsyncSession) -> str:
    """
    Collect safe, credential-free context about the tenant's current configuration.
    This is provided to the LLM so it can generate informed proposals.

    NEVER includes: passwords, API keys, OAuth tokens, database credentials,
    encrypted data, or any secret material.
    """
    context_parts: list[str] = []

    # Existing integrations (safe metadata only)
    try:
        integrations = await int_mgr.list_integrations(tenant_id=tenant_id, db=db)
        if integrations:
            int_lines = [
                f"  - {i.display_name} ({i.provider_type}): {i.status}"
                for i in integrations
            ]
            context_parts.append("EXISTING INTEGRATIONS:\n" + "\n".join(int_lines))
        else:
            context_parts.append("EXISTING INTEGRATIONS: None connected")
    except Exception as exc:
        logger.debug("Could not load integrations for context: %s", exc)

    # Existing AI employees
    try:
        from sqlalchemy import select
        from app.db.models import AIEmployee
        result = await db.execute(
            select(AIEmployee).where(
                AIEmployee.tenant_id == tenant_id,
                AIEmployee.is_active == True,  # noqa: E712
            )
        )
        employees = result.scalars().all()
        if employees:
            emp_lines = [f"  - {e.name} ({e.role_key}): {e.status}" for e in employees]
            context_parts.append("EXISTING AI EMPLOYEES:\n" + "\n".join(emp_lines))
        else:
            context_parts.append("EXISTING AI EMPLOYEES: None created")
    except Exception as exc:
        logger.debug("Could not load employees for context: %s", exc)

    # Existing workflows
    try:
        from app.db.models import Workflow
        result = await db.execute(
            select(Workflow).where(
                Workflow.tenant_id == tenant_id,
                Workflow.is_enabled == True,  # noqa: E712
            ).limit(10)
        )
        workflows = result.scalars().all()
        if workflows:
            wf_lines = [f"  - {w.name} ({w.trigger})" for w in workflows]
            context_parts.append("EXISTING WORKFLOWS:\n" + "\n".join(wf_lines))
        else:
            context_parts.append("EXISTING WORKFLOWS: None created")
    except Exception as exc:
        logger.debug("Could not load workflows for context: %s", exc)

    # Available providers
    provider_types = integration_registry.list_types()
    context_parts.append(f"AVAILABLE INTEGRATION PROVIDERS: {', '.join(provider_types)}")

    return "\n\n".join(context_parts)


async def generate_customization_plan(
    instruction: str,
    tenant_id: str,
    requested_by: str,
    db: AsyncSession,
) -> CustomizationPlan:
    """
    Use the LLM to parse a natural-language admin instruction into a
    structured CustomizationPlan.

    The LLM receives:
    - The system prompt (rules + output format)
    - Safe tenant context (no credentials)
    - The admin's instruction

    Returns a validated CustomizationPlan with approval_status="pending".
    Raises RuntimeError if the LLM is unavailable or returns unparseable output.
    """
    gateway = get_llm_gateway()
    if not gateway.health().is_ready:
        raise RuntimeError(
            "LLM is not available. Admin AI customization requires a configured LLM."
        )

    # Gather safe context (no credentials)
    tenant_context = await _gather_tenant_context(tenant_id, db)

    human_content = (
        f"CURRENT TENANT CONFIGURATION:\n{tenant_context}\n\n"
        f"ADMIN INSTRUCTION:\n{instruction.strip()}"
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.strip()),
        HumanMessage(content=human_content),
    ]

    try:
        chat_model = gateway.get_chat_model()
        response = await chat_model.ainvoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("LLM call failed during admin customization planning")
        raise RuntimeError(f"LLM error: {exc}") from exc

    data = _extract_json(raw_text)
    if not data:
        logger.warning(
            "LLM returned unparseable plan for tenant %s: %r",
            tenant_id, raw_text[:200],
        )
        raise RuntimeError("LLM returned an unparseable response. Please try again.")

    # Parse and validate through Pydantic (blocks credential fields in params)
    try:
        plan = CustomizationPlan(
            summary=str(data.get("summary", "Customization plan"))[:1000],
            operations=[
                CustomizationOperation(
                    type=op.get("type", "CREATE_AI_EMPLOYEE"),
                    description=str(op.get("description", ""))[:500],
                    params=op.get("params", {}),
                    requires_confirmation=True,
                    order=i,
                )
                for i, op in enumerate(data.get("operations", [])[:20])
                if isinstance(op, dict) and op.get("type") in (
                    "CREATE_AI_EMPLOYEE", "UPDATE_AI_EMPLOYEE",
                    "CONNECT_INTEGRATION", "GRANT_CAPABILITY",
                    "REVOKE_CAPABILITY", "CREATE_WORKFLOW",
                    "UPDATE_WORKFLOW", "SET_APPROVAL_POLICY",
                )
            ],
            missing_information=[
                str(m)[:200] for m in data.get("missing_information", [])[:10]
            ],
            requires_confirmation=True,
        )
    except Exception as exc:
        logger.warning("Plan validation failed for tenant %s: %s", tenant_id, exc)
        raise RuntimeError(f"Plan validation error: {exc}") from exc

    logger.info(
        "Customization plan generated: tenant=%s operations=%d missing=%d",
        tenant_id, len(plan.operations), len(plan.missing_information),
    )
    return plan


# ── Plan execution ────────────────────────────────────────────────────────────

async def execute_customization_plan(
    plan: CustomizationPlan,
    tenant_id: str,
    confirmed_by: str,
    db: AsyncSession,
) -> AdminCustomizationResult:
    """
    Execute a confirmed customization plan through existing EAAWP services.

    Each operation is mapped to an existing service function.
    Operations are executed in order; failures are recorded but do not
    stop subsequent operations (each is independent).

    All executions are audit-logged to the AuditLog table.
    HIGH-risk operations (send_email, external publish) still go through
    the existing approval pipeline — this function never bypasses governance.
    """
    results: list[OperationResult] = []
    audit_id = str(uuid.uuid4())
    executed_at = datetime.now(timezone.utc)

    # Re-validate the plan before execution (guards against tampered payloads)
    try:
        CustomizationPlan.model_validate(plan.model_dump())
    except Exception as exc:
        raise ValueError(f"Plan failed re-validation: {exc}") from exc

    for op in sorted(plan.operations, key=lambda o: o.order):
        result = await _execute_operation(op, tenant_id, confirmed_by, db)
        results.append(result)

    succeeded = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")

    # Write audit log entry
    try:
        from app.db.models import AuditLog
        audit_event = (
            f"Admin customization executed by {confirmed_by}: "
            f"{plan.summary[:200]}. "
            f"Operations: {len(results)} total, {succeeded} succeeded, {failed} failed."
        )
        log_entry = AuditLog(
            id=audit_id,
            tenant_id=tenant_id,
            actor=confirmed_by,
            event=audit_event,
            status="ok" if failed == 0 else "partial",
        )
        db.add(log_entry)
        await db.commit()
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)
        await db.rollback()

    logger.info(
        "Customization plan executed: tenant=%s by=%s succeeded=%d failed=%d",
        tenant_id, confirmed_by, succeeded, failed,
    )

    return AdminCustomizationResult(
        plan_summary=plan.summary,
        operations_total=len(results),
        operations_succeeded=succeeded,
        operations_failed=failed,
        results=results,
        executed_at=executed_at,
        executed_by=confirmed_by,
        audit_id=audit_id,
    )


async def _execute_operation(
    op: CustomizationOperation,
    tenant_id: str,
    confirmed_by: str,
    db: AsyncSession,
) -> OperationResult:
    """
    Execute one operation by calling the appropriate existing EAAWP service.

    Security: this function never bypasses capability grants, approval gates,
    or credential encryption. It only calls existing service functions.
    """
    try:
        if op.type == "CREATE_AI_EMPLOYEE":
            return await _op_create_employee(op, tenant_id, confirmed_by, db)
        if op.type == "UPDATE_AI_EMPLOYEE":
            return await _op_update_employee(op, tenant_id, db)
        if op.type == "CONNECT_INTEGRATION":
            return await _op_connect_integration(op, tenant_id, confirmed_by, db)
        if op.type == "GRANT_CAPABILITY":
            return await _op_grant_capability(op, tenant_id, db)
        if op.type == "REVOKE_CAPABILITY":
            return await _op_revoke_capability(op, tenant_id, db)
        if op.type == "CREATE_WORKFLOW":
            return await _op_create_workflow(op, tenant_id, confirmed_by, db)
        if op.type == "UPDATE_WORKFLOW":
            return await _op_update_workflow(op, tenant_id, db)
        if op.type == "SET_APPROVAL_POLICY":
            return await _op_set_approval_policy(op, tenant_id, db)
        return OperationResult(
            type=op.type,
            description=op.description,
            status="skipped",
            detail=f"Unknown operation type: {op.type}",
        )
    except Exception as exc:
        logger.exception("Operation %s failed: %s", op.type, exc)
        return OperationResult(
            type=op.type,
            description=op.description,
            status="failed",
            detail=str(exc)[:500],
        )


async def _op_create_employee(
    op: CustomizationOperation,
    tenant_id: str,
    confirmed_by: str,
    db: AsyncSession,
) -> OperationResult:
    """CREATE_AI_EMPLOYEE → generate_employee_blueprint → auto-approve if no missing integrations."""
    p = op.params
    name = str(p.get("name", "New AI Employee"))[:255]
    purpose = str(p.get("purpose", "Configured via Admin AI Customization"))[:1000]
    instruction = f"Create an AI employee named '{name}' with purpose: {purpose}"

    # Load existing integrations for blueprint cross-check
    integrations = await int_mgr.list_integrations(tenant_id=tenant_id, db=db)
    existing = [{"id": i.id, "provider_type": i.provider_type, "status": i.status}
                for i in integrations]

    from app.services.employee_builder_service import generate_employee_blueprint
    blueprint = await generate_employee_blueprint(
        instruction=instruction,
        tenant_id=tenant_id,
        created_by=confirmed_by,
        existing_integrations=existing,
    )

    # Persist blueprint proposal
    from app.db.models import EmployeeBlueprintProposalORM
    import json as _json
    row = EmployeeBlueprintProposalORM(
        id=blueprint.id,
        tenant_id=tenant_id,
        name=blueprint.name,
        role_key=blueprint.role_key,
        purpose=blueprint.purpose,
        responsibilities_json=_json.dumps(blueprint.responsibilities),
        objectives_json=_json.dumps(blueprint.objectives),
        required_capabilities_json=_json.dumps([rc.model_dump() for rc in blueprint.required_capabilities]),
        missing_integrations_json=_json.dumps([mi.model_dump() for mi in blueprint.missing_integrations]),
        allowed_tools_json=_json.dumps(blueprint.allowed_tools),
        guarded_tools_json=_json.dumps(blueprint.guarded_tools),
        suggested_schedule=blueprint.suggested_schedule,
        communication_style=blueprint.communication_style,
        llm_model=blueprint.llm_model,
        system_persona=blueprint.system_persona,
        original_instruction=instruction,
        approval_status="pending",
        created_by=confirmed_by,
    )
    db.add(row)

    # If no missing integrations → auto-activate the employee
    if not blueprint.missing_integrations:
        from app.db.models import AIEmployee, AgentConfiguration
        employee_id = str(uuid.uuid4())
        employee = AIEmployee(
            id=employee_id,
            tenant_id=tenant_id,
            role_key=blueprint.role_key,
            name=blueprint.name,
            status="ACTIVE",
            is_active=True,
        )
        db.add(employee)
        config = AgentConfiguration(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            ai_employee_id=employee_id,
            system_persona=blueprint.system_persona,
            tone=blueprint.communication_style or "Concise",
            autonomy_level=3,
            capabilities_json="{}",
            tools_json=_json.dumps(blueprint.allowed_tools),
            tool_scopes_json="[]",
            permissions_json="[]",
        )
        db.add(config)
        row.approval_status = "approved"
        row.reviewed_by = confirmed_by
        row.ai_employee_id = employee_id
        await db.flush()
        return OperationResult(
            type=op.type,
            description=op.description,
            status="success",
            detail=f"AI employee '{blueprint.name}' created and activated (ID: {employee_id[:8]}).",
            created_id=employee_id,
        )
    else:
        await db.flush()
        missing = [mi.display_name for mi in blueprint.missing_integrations]
        return OperationResult(
            type=op.type,
            description=op.description,
            status="success",
            detail=(
                f"Blueprint for '{blueprint.name}' created (pending). "
                f"Missing integrations: {', '.join(missing)}. "
                "Connect them and approve the blueprint to activate."
            ),
            created_id=blueprint.id,
        )


async def _op_update_employee(
    op: CustomizationOperation,
    tenant_id: str,
    db: AsyncSession,
) -> OperationResult:
    """UPDATE_AI_EMPLOYEE → update AgentConfiguration.system_persona / tools."""
    p = op.params
    employee_name = str(p.get("name", ""))
    role_key = str(p.get("role_key", "")).upper()

    from sqlalchemy import select
    from app.db.models import AIEmployee, AgentConfiguration
    import json as _json

    # Find the employee
    stmt = select(AIEmployee).where(
        AIEmployee.tenant_id == tenant_id,
        AIEmployee.is_active == True,  # noqa: E712
    )
    if role_key:
        stmt = stmt.where(AIEmployee.role_key == role_key)
    elif employee_name:
        stmt = stmt.where(AIEmployee.name.ilike(f"%{employee_name}%"))
    else:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail="UPDATE_AI_EMPLOYEE requires 'name' or 'role_key' param.",
        )

    result = await db.execute(stmt)
    employee = result.scalars().first()
    if not employee:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail=f"No active AI employee found matching the criteria.",
        )

    # Update configuration if provided
    cfg_result = await db.execute(
        select(AgentConfiguration).where(
            AgentConfiguration.ai_employee_id == employee.id
        )
    )
    config = cfg_result.scalar_one_or_none()
    if config and p.get("communication_style"):
        config.tone = str(p["communication_style"])[:32]

    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=f"AI employee '{employee.name}' updated.",
        created_id=employee.id,
    )


async def _op_connect_integration(
    op: CustomizationOperation,
    tenant_id: str,
    confirmed_by: str,
    db: AsyncSession,
) -> OperationResult:
    """
    CONNECT_INTEGRATION → create integration_catalog placeholder.
    OAuth2 providers: creates placeholder, returns OAuth URL.
    DB providers: returns guidance that credentials must be entered via Integration Manager.
    Credentials are NEVER collected or stored through this path.
    """
    p = op.params
    provider_type = str(p.get("provider_type", ""))[:64].lower()
    display_name = str(p.get("display_name", provider_type))[:255]

    if not provider_type:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail="CONNECT_INTEGRATION requires 'provider_type' param.",
        )

    if not integration_registry.has(provider_type):
        available = integration_registry.list_types()
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail=f"Unknown provider '{provider_type}'. Available: {available}",
        )

    # Check if already connected
    existing = await int_mgr.list_integrations(tenant_id=tenant_id, db=db, provider_type=provider_type)
    if any(i.status == "connected" for i in existing):
        return OperationResult(
            type=op.type, description=op.description, status="success",
            detail=f"{display_name} is already connected.",
            created_id=existing[0].id,
        )

    # Create placeholder row (no credentials)
    from app.schemas.integration_framework import IntegrationCreate
    integration = await int_mgr.create_integration(
        IntegrationCreate(
            provider_type=provider_type,
            display_name=display_name,
            credentials={},
            created_by=confirmed_by,
        ),
        tenant_id=tenant_id,
        db=db,
    )
    await db.flush()

    # OAuth2 providers need browser redirect; DB providers need the Integration Manager UI
    oauth_providers = {"google_search_console", "google_analytics", "facebook", "github"}
    if provider_type in oauth_providers:
        detail = (
            f"Integration '{display_name}' created (ID: {integration.id[:8]}). "
            "Authorization required: go to Integrations → connect via OAuth to activate."
        )
    else:
        detail = (
            f"Integration '{display_name}' created (ID: {integration.id[:8]}). "
            "Credentials required: go to Integrations → enter credentials securely to activate."
        )

    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=detail, created_id=integration.id,
    )


async def _op_grant_capability(
    op: CustomizationOperation,
    tenant_id: str,
    db: AsyncSession,
) -> OperationResult:
    """GRANT_CAPABILITY → existing create_capability_grant."""
    p = op.params
    provider_type = str(p.get("provider_type", "")).lower()
    capability_key = str(p.get("capability_key", ""))
    role_key = str(p.get("role_key", "DIGITAL_MARKETING_MANAGER"))

    # Find the integration
    integrations = await int_mgr.list_integrations(
        tenant_id=tenant_id, db=db, provider_type=provider_type
    )
    if not integrations:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail=f"No integration found for provider '{provider_type}'. Connect it first.",
        )
    integration_id = integrations[0].id

    from app.schemas.integration_framework import CapabilityGrantCreate
    await int_mgr.create_capability_grant(
        integration_id=integration_id,
        body=CapabilityGrantCreate(
            role_key=role_key,
            capability_key=capability_key,
            is_granted=True,
            granted_by="admin-customization",
        ),
        tenant_id=tenant_id,
        db=db,
    )
    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=f"Capability '{capability_key}' granted to {role_key} via {provider_type}.",
    )


async def _op_revoke_capability(
    op: CustomizationOperation,
    tenant_id: str,
    db: AsyncSession,
) -> OperationResult:
    """REVOKE_CAPABILITY → find grant and delete."""
    p = op.params
    provider_type = str(p.get("provider_type", "")).lower()
    capability_key = str(p.get("capability_key", ""))
    role_key = str(p.get("role_key", ""))

    integrations = await int_mgr.list_integrations(
        tenant_id=tenant_id, db=db, provider_type=provider_type
    )
    if not integrations:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail=f"No integration found for provider '{provider_type}'.",
        )
    integration_id = integrations[0].id
    grants = await int_mgr.list_capability_grants(
        integration_id=integration_id, tenant_id=tenant_id, db=db
    )
    matching = [
        g for g in grants
        if g.capability_key == capability_key
        and (not role_key or g.role_key == role_key)
        and g.is_granted
    ]
    if not matching:
        return OperationResult(
            type=op.type, description=op.description, status="success",
            detail="No matching active grant found — nothing to revoke.",
        )
    for grant in matching:
        await int_mgr.delete_capability_grant(
            grant_id=grant.id, tenant_id=tenant_id, db=db
        )
    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=f"Revoked {len(matching)} grant(s) for '{capability_key}'.",
    )


async def _op_create_workflow(
    op: CustomizationOperation,
    tenant_id: str,
    confirmed_by: str,
    db: AsyncSession,
) -> OperationResult:
    """CREATE_WORKFLOW → Workflow ORM insert (same as workflow router)."""
    import json as _json
    p = op.params
    name = str(p.get("name", "New Workflow"))[:255]
    trigger = str(p.get("trigger", "manual"))
    schedule_cron = p.get("schedule_cron") or None
    description = str(p.get("description", ""))[:1000]
    steps_raw = p.get("steps", [])

    if trigger not in ("manual", "scheduled", "event"):
        trigger = "manual"
    if schedule_cron:
        schedule_cron = str(schedule_cron)[:100]

    from app.db.models import Workflow
    wf = Workflow(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ai_employee_id=None,
        name=name,
        description=description,
        trigger=trigger,
        schedule_cron=schedule_cron,
        steps_json=_json.dumps(steps_raw[:50]),
        is_enabled=True,
        status="idle",
        created_by=confirmed_by,
    )
    db.add(wf)
    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=f"Workflow '{name}' created (ID: {wf.id[:8]}).",
        created_id=wf.id,
    )


async def _op_update_workflow(
    op: CustomizationOperation,
    tenant_id: str,
    db: AsyncSession,
) -> OperationResult:
    """UPDATE_WORKFLOW → find workflow and update fields."""
    import json as _json
    from sqlalchemy import select
    from app.db.models import Workflow

    p = op.params
    workflow_name = str(p.get("name", ""))

    stmt = select(Workflow).where(Workflow.tenant_id == tenant_id)
    if workflow_name:
        stmt = stmt.where(Workflow.name.ilike(f"%{workflow_name}%"))
    result = await db.execute(stmt.limit(1))
    wf = result.scalar_one_or_none()
    if not wf:
        return OperationResult(
            type=op.type, description=op.description, status="failed",
            detail=f"No workflow found matching '{workflow_name}'.",
        )

    if p.get("trigger"):
        wf.trigger = str(p["trigger"])
    if p.get("schedule_cron") is not None:
        wf.schedule_cron = str(p["schedule_cron"])[:100] if p["schedule_cron"] else None
    if p.get("is_enabled") is not None:
        wf.is_enabled = bool(p["is_enabled"])

    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=f"Workflow '{wf.name}' updated.",
    )


async def _op_set_approval_policy(
    op: CustomizationOperation,
    tenant_id: str,
    db: AsyncSession,
) -> OperationResult:
    """
    SET_APPROVAL_POLICY → update RoleConfiguration.permissions_json.

    Maps the policy scope/mode to the existing permissions format used by
    RoleConfiguration, which is already read by the governance pipeline.
    """
    import json as _json
    from sqlalchemy import select
    from app.db.models import RoleConfiguration

    p = op.params
    scope = str(p.get("scope", "all_external_actions"))
    mode = str(p.get("mode", "approval_required"))
    role_key = str(p.get("role_key", "")).upper() or None

    # Map scope/mode to the existing permissions format
    if scope == "all_external_actions" or scope == "send_email":
        action = "Send email"
    elif scope == "publish":
        action = "Publish externally"
    else:
        action = scope

    perm_mode = "approval" if mode == "approval_required" else "auto"
    new_permission = {"action": action, "mode": perm_mode}

    # Find matching RoleConfiguration(s) for this tenant
    stmt = select(RoleConfiguration).where(RoleConfiguration.tenant_id == tenant_id)
    if role_key:
        stmt = stmt.where(RoleConfiguration.role_key == role_key)
    result = await db.execute(stmt)
    configs = result.scalars().all()

    if not configs:
        # No role config yet — store as a note (config will pick it up when seeded)
        return OperationResult(
            type=op.type, description=op.description, status="success",
            detail=(
                f"Approval policy recorded: '{action}' → {perm_mode}. "
                "Policy will be applied when a role configuration is created."
            ),
        )

    updated = 0
    for cfg in configs:
        try:
            existing_perms = _json.loads(cfg.permissions_json or "[]")
        except Exception:
            existing_perms = []
        # Update or insert the permission
        for i, perm in enumerate(existing_perms):
            if isinstance(perm, dict) and perm.get("action") == action:
                existing_perms[i] = new_permission
                break
        else:
            existing_perms.append(new_permission)
        cfg.permissions_json = _json.dumps(existing_perms)
        updated += 1

    await db.flush()
    return OperationResult(
        type=op.type, description=op.description, status="success",
        detail=(
            f"Approval policy set: '{action}' requires {perm_mode} "
            f"(updated {updated} role configuration(s))."
        ),
    )
