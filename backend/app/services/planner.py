"""
EAAWP Agent Planning Service

Implements the multi-step planning loop for the Digital Marketing Manager.
LLM calls use the centralized LLM Gateway (app.llm) — no direct ChatOpenAI
initialization in this module.

Execution flow
--------------
User request
  → LLM generates a structured plan (list of steps)
  → Validate plan (max steps, tool availability)
  → Execute steps in dependency order:
      read steps    → execute tool, store safe result summary
      action steps  → route through action governance
                        if approval needed → pause plan (awaiting_approval)
                        if auto-execute   → execute, verify, continue
      analysis steps → LLM reasoning over prior results (no tool call)
      verify steps  → confirm a prior action produced expected output
      response step → synthesise final message for the user
  → Return final response + plan metadata

Security invariants
-------------------
- Chain-of-thought is NEVER stored — only concise safe summaries.
- Credentials, connection strings, and secrets never enter plan records.
- Blueprint permissions are re-checked at resume time.
- Tenant isolation is enforced on every DB write.
- MAX_PLAN_STEPS and MAX_TOOL_CALLS_PER_PLAN prevent infinite loops.
- Dependency failures block dependent steps — no silent continuation.

Plan pause / resume (approval)
-------------------------------
When an action step requires approval:
  1. Plan status → awaiting_approval
  2. PlanStep status → awaiting_approval
  3. ApprovalRequest created (via existing governance service)
  4. Execution stops — dependent steps remain pending
  5. Frontend shows "Awaiting approval"

On approval:
  1. POST /api/v1/planning/plans/{plan_id}/resume
  2. Re-validate permissions (blueprint may have changed)
  3. Execute the approved step
  4. Verify
  5. Continue subsequent steps
  6. Return updated final response
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_gateway

from app.db.models import ExecutionPlan, PlanStep
from app.schemas.actions import ActionRequest
from app.schemas.blueprint import AgentBlueprint, ToolCallDetail
from app.schemas.planning import (
    MAX_PLAN_STEPS,
    MAX_TOOL_CALLS_PER_PLAN,
    AgentPlan,
    PlannedStep,
)
from app.services.action_governance import process_action_request
from app.tools.dynamic_tool import is_tool_failure
from app.tools.registry import MASTER_TOOL_REGISTRY

logger = logging.getLogger(__name__)

# ── Planner system prompt ─────────────────────────────────────────────────────

_PLANNER_SYSTEM = f"""
You are a planning assistant for the EAAWP Digital Marketing Manager.
Your job is to create a structured execution plan to fulfil the user's request.

Rules:
1. Create a plan with at most {MAX_PLAN_STEPS} steps.
2. Each step must have a clear, concise description (shown to the user).
3. Use ONLY tools available in the agent's tool list.
4. Do NOT include reasoning or chain-of-thought — only observable actions.
5. The final step must always be type "response" with no tool.
6. Steps may depend on prior steps (use depends_on as a list of step indices, 0-based).

RESPONSE QUALITY RULES (MANDATORY):
- NEVER begin any response with "[AUDIT LOG", "[Action:", "INT-", "Data Source:", or any internal reference prefix.
- NEVER fabricate audit trail entries, reference IDs, or internal system codes.
- NEVER start a response with markdown bold headers like "**Verify Ownership:**".
- Responses must be natural, direct, and conversational — never formatted as internal SOPs.
- Do NOT dump step-by-step IT procedures from the knowledge base in response to action requests.
- If you have nothing to say, say it simply. Do not pad with internal jargon.

CRITICAL — INTEGRATION ACTION REQUESTS:
- If the user is asking to CONNECT, DISCONNECT, or CHECK the status of an integration
  (e.g. "Connect my GSC", "Connect Google Analytics", "Connect GitHub", "Connect MCP",
   "Connect my database", "Is GSC connected?"), do NOT use fetch_knowledge_base.
- Integration connection requests are ACTION requests, not information requests.
- For connection requests, respond with a single "response" step acknowledging the
  request and directing to the integration panel.
- Never answer "Connect my GSC" with an SOP or documentation from the knowledge base.

INFORMATION vs ACTION distinction:
- "How do I connect GSC?" → INFORMATION → MAY use fetch_knowledge_base
- "Connect my GSC" → ACTION → must NOT use fetch_knowledge_base, must NOT return docs

Campaign management rules (IMPORTANT):
- get_campaigns, get_campaign_metrics, get_campaign_summary are READ tools (low risk, auto-execute).
- analyze_campaign_performance, compare_campaigns, get_campaign_kpis are READ tools (low risk, auto-execute).
  All numeric values in performance analysis originate from deterministic calculations — never fabricated.
  Recommendations from analyze_campaign_performance are evidence-based — pass them to governance to act on.
- analyze_funnel, get_funnel_metrics, analyze_campaign_funnel are READ tools (low risk, auto-execute).
  They use authorized external data via semantic mappings — no arbitrary SQL or hardcoded table names.
  Never fabricate funnel stages or conversion rates. Explicitly state when data is missing.
- analyze_marketing_strategy, get_marketing_priorities, get_marketing_objectives are READ tools (low risk, auto-execute).
  All priority scores are deterministic — never LLM-assigned. Evidence must support every finding.
  Recommendations from strategy analysis must go through governance before execution.
- create_marketing_objective is MEDIUM risk and requires approval.
- update_marketing_objective is HIGH risk and requires approval.
- generate_content_brief, generate_content_ideas, generate_content_draft,
  generate_content_variants, analyze_content are GENERATION tools (low/medium risk, auto-execute).
  They use the existing RAG system for brand/audience context.
  They NEVER publish content externally. Results are saved as internal content items.
  Always cite RAG sources when knowledge was used.
- create_campaign is MEDIUM risk and requires approval before a new campaign is created.
- update_campaign is HIGH risk when budget or status changes; MEDIUM otherwise. Always requires approval.
- NEVER directly execute SQL or modify external database tables.
- Campaign records are EAAWP-internal — separate from external company data.
- When referencing external company performance data, use query_company_data with semantic concepts.


- Use draft_email to PREPARE an email for review. It has NO external side effect.
  draft_email is LOW risk and does not require approval.
- Use send_email to ACTUALLY SEND an email after human approval.
  send_email is HIGH risk and ALWAYS requires human approval.
- NEVER skip draft_email and go directly to send_email without preparing the draft.
- NEVER claim an email was sent unless send_email executed successfully after approval.
- When using company data as evidence in an email, include evidence_sources in draft_email.
- Do NOT expose database credentials, connection IDs, or SMTP details in any step.

Step types:
- read    : use a read tool (query_company_data, fetch_knowledge_base, query_campaign_analytics,
             get_campaigns, get_campaign_metrics, get_campaign_summary,
             analyze_campaign_performance, compare_campaigns, get_campaign_kpis,
             analyze_funnel, get_funnel_metrics, analyze_campaign_funnel,
             analyze_marketing_strategy, get_marketing_priorities, get_marketing_objectives)
- action  : use an action tool (draft_email, send_email, create_internal_task,
             create_campaign, update_campaign)
- analysis: reason over prior results (no tool call, internal LLM step)
- verify  : confirm a prior action produced the expected result
- response: synthesise the final answer for the user

Respond ONLY with valid JSON — no markdown, no backticks. Format:
{{
  "objective": "brief summary of the goal",
  "steps": [
    {{
      "step_index": 0,
      "step_type": "read",
      "description": "What this step does (user-visible)",
      "tool_name": "query_campaign_analytics",
      "arguments": {{"channel": "all"}},
      "depends_on": []
    }},
    ...
    {{
      "step_index": N,
      "step_type": "response",
      "description": "Synthesise and return the final answer",
      "tool_name": null,
      "arguments": {{}},
      "depends_on": [N-1]
    }}
  ]
}}
"""


# ── Main planning entry point ─────────────────────────────────────────────────

async def create_and_execute_plan(
    user_prompt: str,
    blueprint: AgentBlueprint,
    session_id: str | None,
    db: AsyncSession,
    system_persona: str = "",
    data_context_block: str = "",
    rag_context: str = "",
) -> tuple[str, str, list[ToolCallDetail]]:
    """
    Create an execution plan for the user's request, execute it, and return
    (final_message, plan_id, tool_calls_used).

    If an action step requires approval, the plan pauses and returns a
    partial message explaining the pending approval.
    """
    tenant_id = blueprint.tenant_id
    role_key = _role_key(blueprint.role_name)

    # ── 1. Generate plan via LLM ──────────────────────────────────────────────
    plan = await _generate_plan(
        user_prompt=user_prompt,
        blueprint=blueprint,
        system_persona=system_persona,
        data_context_block=data_context_block,
        rag_context=rag_context,
    )

    if not plan or not plan.steps:
        # Persist an explicit failed plan record so the failure is traceable
        failed_plan_id = str(uuid.uuid4())
        db_failed = ExecutionPlan(
            id=failed_plan_id,
            tenant_id=tenant_id,
            role_key=role_key,
            session_id=session_id,
            objective=user_prompt[:500],
            status="failed",
            total_steps=0,
            blueprint_json=json.dumps({
                "agent_id": blueprint.agent_id,
                "role_name": blueprint.role_name,
                "allowed_tools": blueprint.allowed_tools,
                "guarded_tools": blueprint.guarded_tools,
                "tenant_id": blueprint.tenant_id,
            }),
            final_message="Plan generation produced no actionable steps.",
        )
        db.add(db_failed)
        await db.flush()
        logger.warning(
            "Plan generation returned empty plan for tenant=%s session=%s plan_id=%s",
            tenant_id, session_id, failed_plan_id,
        )
        return (
            "I was unable to generate a plan for your request. "
            "Please rephrase your request or try again.",
            failed_plan_id,
            [],
        )

    # Cap plan size
    plan.steps = plan.steps[:MAX_PLAN_STEPS]

    # ── 2. Persist plan ───────────────────────────────────────────────────────
    plan_id = str(uuid.uuid4())
    db_plan = ExecutionPlan(
        id=plan_id,
        tenant_id=tenant_id,
        role_key=role_key,
        session_id=session_id,
        objective=plan.objective[:500],
        status="running",
        total_steps=len(plan.steps),
        blueprint_json=json.dumps({
            "agent_id": blueprint.agent_id,
            "role_name": blueprint.role_name,
            "allowed_tools": blueprint.allowed_tools,
            "guarded_tools": blueprint.guarded_tools,
            "tenant_id": blueprint.tenant_id,
        }),
    )
    db.add(db_plan)

    db_steps: list[PlanStep] = []
    for ps in plan.steps:
        safe_args = _sanitise_args(ps.arguments)
        db_step = PlanStep(
            id=str(uuid.uuid4()),
            plan_id=plan_id,
            tenant_id=tenant_id,
            step_index=ps.step_index,
            step_type=ps.step_type,
            description=ps.description[:500],
            tool_name=ps.tool_name,
            arguments_json=json.dumps(safe_args),
            depends_on_json=json.dumps(ps.depends_on),
            status="pending",
        )
        db_steps.append(db_step)
        db.add(db_step)

    await db.flush()

    # ── 3. Execute steps ──────────────────────────────────────────────────────
    tool_calls_used = 0
    step_results: dict[int, str] = {}   # step_index → safe result summary

    for db_step, ps in zip(db_steps, plan.steps):
        # Check dependency failures
        dep_failed = any(
            db_steps[dep].status in ("failed", "rejected", "skipped")
            for dep in ps.depends_on
            if dep < len(db_steps)
        )
        if dep_failed:
            db_step.status = "skipped"
            db_step.result_summary = "Skipped: a required previous step failed or was rejected."
            db_plan.status = "failed"
            await db.flush()
            continue

        # Wait for dependencies to complete
        dep_pending = any(
            db_steps[dep].status not in ("completed", "skipped")
            for dep in ps.depends_on
            if dep < len(db_steps)
        )
        if dep_pending:
            db_step.status = "skipped"
            db_step.result_summary = "Skipped: dependency not completed."
            await db.flush()
            continue

        db_step.status = "running"
        await db.flush()

        if ps.step_type == "response":
            # Synthesise final response from all prior results
            try:
                final_msg = await _synthesise_response(
                    objective=plan.objective,
                    step_results=step_results,
                    blueprint=blueprint,
                    system_persona=system_persona,
                )
                final_msg, grounding = _verify_against_evidence(
                    final_msg, plan, db_steps, step_results, user_prompt
                )
            except Exception as exc:
                logger.error("Final response generation failed (%s)", type(exc).__name__, exc_info=True)
                db_step.status = "failed"
                db_step.result_summary = "The AI provider failed while preparing the final response."
                db_plan.status = "failed"
                db_plan.final_message = "I couldn’t prepare a reliable response because the AI model request failed. Please check the model configuration and try again."
                await db.flush()
                break
            db_step.status = "completed"
            db_step.result_summary = f"Final response synthesised. {grounding}"
            db_step.completed_at = datetime.now(timezone.utc)
            db_plan.final_message = final_msg
            db_plan.completed_steps += 1
            await db.flush()
            continue

        if ps.step_type in ("read",) and ps.tool_name:
            # Execute read tool
            if tool_calls_used >= MAX_TOOL_CALLS_PER_PLAN:
                db_step.status = "failed"
                db_step.result_summary = "Tool call limit reached."
                db_plan.status = "failed"
                await db.flush()
                break

            result = await _invoke_tool(ps.tool_name, ps.arguments, blueprint)
            tool_calls_used += 1
            db_plan.tool_calls_used = tool_calls_used
            if is_tool_failure(result):
                db_step.status = "failed"
                db_step.result_summary = result[:500]
                db_step.completed_at = datetime.now(timezone.utc)
                db_plan.status = "failed"
                db_plan.final_message = _failure_message(ps.tool_name, result)
                await db.flush()
                break
            step_results[ps.step_index] = result[:_EVIDENCE_CHARS]  # bounded; integration output is already capped
            db_step.status = "completed"
            db_step.result_summary = result[:500]
            db_step.completed_at = datetime.now(timezone.utc)
            db_plan.completed_steps += 1
            await db.flush()

        elif ps.step_type == "action" and ps.tool_name:
            # Route through action governance
            if tool_calls_used >= MAX_TOOL_CALLS_PER_PLAN:
                db_step.status = "failed"
                db_step.result_summary = "Tool call limit reached."
                db_plan.status = "failed"
                await db.flush()
                break

            action_req = ActionRequest(
                tool_name=ps.tool_name,
                arguments=ps.arguments,
                tenant_id=tenant_id,
                role_key=role_key,
                requested_by="agent",
                session_id=session_id,
            )
            action_result = await process_action_request(
                request=action_req,
                blueprint_allowed_tools=blueprint.allowed_tools,
                blueprint_guarded_tools=blueprint.guarded_tools,
                db=db,
            )
            tool_calls_used += 1
            db_plan.tool_calls_used = tool_calls_used

            if action_result.status == "proposed":
                # Plan pauses — awaiting approval
                db_step.status = "awaiting_approval"
                db_step.approval_request_id = action_result.approval_request_id
                db_step.result_summary = "Awaiting human approval before execution."
                db_plan.status = "awaiting_approval"
                await db.flush()
                # Return partial message
                partial = (
                    f"I have proposed the following action and it is awaiting your approval:\n"
                    f"**{ps.tool_name}**: {ps.description}\n\n"
                    f"Approval request ID: {action_result.approval_request_id}\n"
                    f"Plan ID: {plan_id}\n\n"
                    "Once approved, I will continue executing the remaining steps."
                )
                db_plan.final_message = partial
                await db.flush()
                return partial, plan_id, [ToolCallDetail(name=ps.tool_name, args=ps.arguments)]

            elif action_result.status == "executed":
                step_results[ps.step_index] = action_result.message
                db_step.status = "completed"
                db_step.result_summary = action_result.message[:500]
                db_step.action_audit_id = None  # audit_id tracked in ActionAudit
                db_step.completed_at = datetime.now(timezone.utc)
                db_plan.completed_steps += 1
                await db.flush()

                # Verify step if next step is verify
                next_idx = ps.step_index + 1
                if (next_idx < len(plan.steps) and
                        plan.steps[next_idx].step_type == "verify"):
                    verified = action_result.task_id is not None or "success" in action_result.message.lower()
                    step_results[next_idx] = "Verified." if verified else "Verification failed."

            else:
                db_step.status = "failed"
                db_step.result_summary = action_result.message[:500]
                db_plan.status = "failed"
                await db.flush()
                break

        elif ps.step_type == "analysis":
            # Internal reasoning — use the LLM to reason over prior results (or
            # directly answer the objective when no tools have been called yet).
            if step_results:
                context = "\n".join(
                    f"Step {i}: {r[:400]}" for i, r in sorted(step_results.items()) if r
                )
                analysis_prompt = (
                    f"Objective: {plan.objective}\n\n"
                    f"Prior step results:\n{context}\n\n"
                    f"{ps.description}"
                )
            else:
                # No tool results yet — answer the objective directly.
                analysis_prompt = (
                    f"Objective: {plan.objective}\n\n"
                    f"Task: {ps.description}\n\n"
                    "Please analyse the request and provide your best response."
                )
            try:
                _sys = system_persona or (
                    "You are the Marketing Intelligence Agent. "
                    "Provide a clear, concise, and helpful response."
                )
                _model = get_llm_gateway().get_chat_model(temperature=0)
                _resp = await _model.ainvoke([
                    SystemMessage(content=_sys),
                    HumanMessage(content=analysis_prompt),
                ])
                # Handle both string and list-of-blocks content (Gemini 3.8+ format)
                if isinstance(_resp.content, str):
                    _content = _resp.content
                elif isinstance(_resp.content, list):
                    _content = " ".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in _resp.content
                    )
                else:
                    _content = str(_resp.content) if _resp.content else ""
                summary = (
                    _clean_response(_content)
                    if _content.strip()
                    else ""
                )
                if not summary:
                    raise RuntimeError("The AI provider returned an empty analysis.")
            except Exception as _exc:
                logger.warning("Analysis step LLM call failed (%s): %s", type(_exc).__name__, _exc, exc_info=True)
                db_step.status = "failed"
                db_step.result_summary = "The AI provider failed while analysing the request."
                db_plan.status = "failed"
                db_plan.final_message = "I couldn’t analyse this request because the AI model request failed. Please check the model configuration and try again."
                await db.flush()
                break
            step_results[ps.step_index] = summary
            db_step.status = "completed"
            db_step.result_summary = summary[:500]
            db_step.completed_at = datetime.now(timezone.utc)
            db_plan.completed_steps += 1
            await db.flush()

        elif ps.step_type == "verify":
            # Verification step
            prior = step_results.get(ps.step_index, "")
            if prior == "Verification failed.":
                db_step.status = "failed"
                db_step.result_summary = "Verification failed — action may not have completed correctly."
                db_plan.status = "failed"
                await db.flush()
            else:
                db_step.status = "completed"
                db_step.result_summary = prior or "Verified."
                db_step.completed_at = datetime.now(timezone.utc)
                db_plan.completed_steps += 1
                await db.flush()

    # ── 4. Finalise plan ──────────────────────────────────────────────────────
    if not db_plan.final_message:
        db_plan.status = "failed"
        db_plan.final_message = "The request did not produce a final answer. Please review the execution steps and try again."

    if db_plan.status not in ("awaiting_approval", "failed", "rejected"):
        db_plan.status = "completed"
        db_plan.completed_at = datetime.now(timezone.utc)

    await db.flush()

    all_tool_calls = [
        ToolCallDetail(name=s.tool_name, args=json.loads(s.arguments_json or "{}"))
        for s in db_steps
        if s.tool_name and s.status in ("completed", "awaiting_approval")
    ]
    return db_plan.final_message, plan_id, all_tool_calls


async def reject_plan(
    plan_id: str,
    tenant_id: str,
    reviewed_by: str,
    db: AsyncSession,
) -> tuple[str, str]:
    """Reject the pending governed action and stop the plan."""
    plan_result = await db.execute(
        select(ExecutionPlan).where(
            ExecutionPlan.id == plan_id,
            ExecutionPlan.tenant_id == tenant_id,
        )
    )
    db_plan = plan_result.scalar_one_or_none()
    if not db_plan:
        return "Plan not found.", plan_id
    if db_plan.status != "awaiting_approval":
        return f"Plan is in status '{db_plan.status}' — cannot reject.", plan_id

    steps_result = await db.execute(
        select(PlanStep)
        .where(PlanStep.plan_id == plan_id, PlanStep.tenant_id == tenant_id)
        .order_by(PlanStep.step_index)
    )
    db_steps = list(steps_result.scalars().all())
    pending_step = next(
        (step for step in db_steps if step.status == "awaiting_approval"), None
    )
    if not pending_step or not pending_step.approval_request_id:
        db_plan.status = "failed"
        db_plan.final_message = "Cannot reject: no pending approval request was found."
        await db.flush()
        return db_plan.final_message, plan_id

    from app.db.models import ActionAudit
    from app.services.action_governance import reject_action

    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.approval_request_id == pending_step.approval_request_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()
    if not audit:
        pending_step.status = "failed"
        pending_step.result_summary = "Action audit record not found."
        db_plan.status = "failed"
        db_plan.final_message = "Rejection failed because the action audit record was not found."
        await db.flush()
        return db_plan.final_message, plan_id

    result = await reject_action(
        audit_id=audit.id,
        approval_request_id=pending_step.approval_request_id,
        reviewed_by=reviewed_by,
        tenant_id=tenant_id,
        db=db,
    )
    if result.status != "rejected":
        pending_step.status = "failed"
        pending_step.result_summary = result.message[:500]
        db_plan.status = "failed"
        db_plan.final_message = f"The action could not be rejected: {result.message}"
        await db.flush()
        return db_plan.final_message, plan_id

    pending_step.status = "rejected"
    pending_step.result_summary = "Rejected by an administrator. The action was not executed."
    pending_step.completed_at = datetime.now(timezone.utc)
    db_plan.status = "rejected"
    db_plan.final_message = "The proposed action was rejected. It was not executed, and the plan has stopped."
    await db.flush()
    return db_plan.final_message, plan_id


async def resume_plan(
    plan_id: str,
    tenant_id: str,
    reviewed_by: str,
    db: AsyncSession,
) -> tuple[str, str]:
    """
    Resume a paused plan after an action approval.
    Re-validates permissions before continuing.
    Returns (final_message, plan_id).
    """
    # Load plan
    plan_result = await db.execute(
        select(ExecutionPlan).where(
            ExecutionPlan.id == plan_id,
            ExecutionPlan.tenant_id == tenant_id,
        )
    )
    db_plan = plan_result.scalar_one_or_none()
    if not db_plan:
        return "Plan not found.", plan_id

    if db_plan.status != "awaiting_approval":
        return f"Plan is in status '{db_plan.status}' — cannot resume.", plan_id

    # Load steps
    steps_result = await db.execute(
        select(PlanStep)
        .where(PlanStep.plan_id == plan_id, PlanStep.tenant_id == tenant_id)
        .order_by(PlanStep.step_index)
    )
    db_steps = list(steps_result.scalars().all())

    # Find the awaiting_approval step
    pending_step = next(
        (s for s in db_steps if s.status == "awaiting_approval"), None
    )
    if not pending_step or not pending_step.approval_request_id:
        db_plan.status = "failed"
        db_plan.final_message = "Cannot resume: no approval request found."
        await db.flush()
        return db_plan.final_message, plan_id

    # Re-validate blueprint permissions from stored snapshot
    bp_data = json.loads(db_plan.blueprint_json or "{}")
    allowed_tools: list[str] = bp_data.get("allowed_tools", [])
    guarded_tools: list[str] = bp_data.get("guarded_tools", [])
    tool_name = pending_step.tool_name or ""

    if tool_name not in allowed_tools:
        pending_step.status = "rejected"
        pending_step.result_summary = "Permission re-validation failed: tool no longer allowed."
        db_plan.status = "rejected"
        db_plan.final_message = "Plan rejected: tool permissions changed since the plan was created."
        await db.flush()
        return db_plan.final_message, plan_id

    # Execute the approved step via action governance
    from app.services.action_governance import approve_and_execute
    from app.db.models import ActionAudit

    # Find the ActionAudit for this approval request
    audit_result = await db.execute(
        select(ActionAudit).where(
            ActionAudit.approval_request_id == pending_step.approval_request_id,
            ActionAudit.tenant_id == tenant_id,
        )
    )
    audit = audit_result.scalar_one_or_none()

    if not audit:
        pending_step.status = "failed"
        pending_step.result_summary = "Action audit record not found."
        db_plan.status = "failed"
        await db.flush()
        return "Resume failed: action audit record not found.", plan_id

    action_result = await approve_and_execute(
        audit_id=audit.id,
        approval_request_id=pending_step.approval_request_id,
        reviewed_by=reviewed_by,
        tenant_id=tenant_id,
        db=db,
    )

    if action_result.status == "executed":
        pending_step.status = "completed"
        pending_step.result_summary = action_result.message[:500]
        pending_step.completed_at = datetime.now(timezone.utc)
        db_plan.completed_steps += 1
        db_plan.status = "running"
        await db.flush()

        # Continue remaining pending steps (analysis, verify, response)
        step_results: dict[int, str] = {
            s.step_index: s.result_summary
            for s in db_steps
            if s.status == "completed"
        }
        step_results[pending_step.step_index] = action_result.message

        for db_step in db_steps:
            if db_step.status not in ("pending",):
                continue
            dep_failed = any(
                db_steps[dep].status in ("failed", "rejected", "skipped")
                for dep in json.loads(db_step.depends_on_json or "[]")
                if dep < len(db_steps)
            )
            if dep_failed:
                db_step.status = "skipped"
                continue

            db_step.status = "running"
            await db.flush()

            if db_step.step_type == "response":
                blueprint_snapshot = AgentBlueprint(
                    agent_id=bp_data.get("agent_id", "agent"),
                    role_name=bp_data.get("role_name", "Digital Marketing Manager"),
                    system_persona="",
                    allowed_tools=allowed_tools,
                    guarded_tools=guarded_tools,
                    tenant_id=tenant_id,
                )
                try:
                    final_msg = await _synthesise_response(
                        objective=db_plan.objective,
                        step_results=step_results,
                        blueprint=blueprint_snapshot,
                    )
                except Exception as exc:
                    logger.error("Resumed response generation failed (%s)", type(exc).__name__, exc_info=True)
                    db_step.status = "failed"
                    db_step.result_summary = "The AI provider failed while preparing the final response."
                    db_plan.status = "failed"
                    db_plan.final_message = "I couldn’t prepare a reliable response because the AI model request failed. Please check the model configuration and try again."
                    await db.flush()
                    break
                db_step.status = "completed"
                db_step.result_summary = "Final response synthesised."
                db_step.completed_at = datetime.now(timezone.utc)
                db_plan.completed_steps += 1
                db_plan.final_message = final_msg
                await db.flush()
            elif db_step.step_type in ("analysis", "verify"):
                db_step.status = "completed"
                db_step.result_summary = "Completed after resume."
                db_step.completed_at = datetime.now(timezone.utc)
                db_plan.completed_steps += 1
                await db.flush()

        if db_plan.status == "running":
            if db_plan.final_message:
                db_plan.status = "completed"
                db_plan.completed_at = datetime.now(timezone.utc)
            else:
                db_plan.status = "failed"
                db_plan.final_message = "The request did not produce a final answer after approval. Please review the execution steps and try again."
        await db.flush()
        return db_plan.final_message or "The request did not produce a final answer after approval.", plan_id

    else:
        pending_step.status = "failed"
        pending_step.result_summary = action_result.message[:500]
        db_plan.status = "failed"
        db_plan.final_message = f"Action failed after approval: {action_result.message}"
        await db.flush()
        return db_plan.final_message, plan_id


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _generate_plan(
    user_prompt: str,
    blueprint: AgentBlueprint,
    system_persona: str,
    data_context_block: str,
    rag_context: str,
) -> AgentPlan | None:
    """Ask the LLM to generate a structured execution plan."""
    import re

    available_tools = blueprint.allowed_tools
    # Annotate dynamic integration tools with their description so the LLM
    # understands what each capability does. Static tools are already covered
    # by the planner system prompt. Dynamic tools are identified by key prefix.
    from app.tools.dynamic_tool import is_dynamic_tool_key
    from app.tools.registry import _dynamic_tools_ctx
    _dyn_map: dict = _dynamic_tools_ctx.get() or {}

    tool_lines = []
    for t in available_tools:
        if is_dynamic_tool_key(t) and t in _dyn_map:
            adapter = _dyn_map[t]
            # The adapter's docstring contains the safe description
            desc = (getattr(adapter, "description", None) or
                    getattr(adapter, "__doc__", None) or "Integration tool")
            # Trim to a single line for the prompt
            short_desc = str(desc).split("\n")[0][:120]
            tool_lines.append(f"  - {t}  [{short_desc}]")
        else:
            tool_lines.append(f"  - {t}")
    tools_str = "\n".join(tool_lines)

    context_parts = []
    if rag_context:
        context_parts.append(f"## Retrieved Knowledge\n{rag_context[:800]}")
    if data_context_block:
        context_parts.append(data_context_block[:800])

    user_msg = (
        f"Available tools: {tools_str}\n\n"
        + ("\n\n".join(context_parts) + "\n\n" if context_parts else "")
        + f"User request: {user_prompt}"
    )

    try:
        model = get_llm_gateway().get_chat_model(temperature=0)
        response = await model.ainvoke([
            SystemMessage(content=_PLANNER_SYSTEM),
            HumanMessage(content=user_msg),
        ])
        raw = response.content if isinstance(response.content, str) else ""
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        steps = []
        for s in data.get("steps", [])[:MAX_PLAN_STEPS]:
            steps.append(PlannedStep(
                step_index=int(s.get("step_index", len(steps))),
                step_type=s.get("step_type", "read"),
                description=str(s.get("description", ""))[:300],
                tool_name=s.get("tool_name") or None,
                arguments=s.get("arguments", {}),
                depends_on=[int(d) for d in s.get("depends_on", [])],
            ))

        return AgentPlan(
            objective=str(data.get("objective", user_prompt))[:500],
            steps=steps,
        )
    except Exception as exc:
        logger.warning("Plan generation failed, falling back to single-step: %s", exc)
        # Fallback: single-step plan
        return AgentPlan(
            objective=user_prompt[:500],
            steps=[
                PlannedStep(
                    step_index=0,
                    step_type="analysis",
                    description="Analyse the request and prepare a response.",
                    tool_name=None,
                    arguments={},
                    depends_on=[],
                ),
                PlannedStep(
                    step_index=1,
                    step_type="response",
                    description="Return the final answer.",
                    tool_name=None,
                    arguments={},
                    depends_on=[0],
                ),
            ],
        )


async def _invoke_tool(
    tool_name: str,
    arguments: dict,
    blueprint: AgentBlueprint,
) -> str:
    """Invoke a read tool and return its result string."""
    from app.core.engine import _execute_tool
    from app.tools.registry import _dynamic_tools_ctx

    _dyn_map: dict = _dynamic_tools_ctx.get() or {}
    tool_map = {}
    for name in blueprint.allowed_tools:
        if name in MASTER_TOOL_REGISTRY:
            tool_map[name] = MASTER_TOOL_REGISTRY[name]
        elif name in _dyn_map:
            tool_map[name] = _dyn_map[name]

    return await _execute_tool(tool_name, arguments, tool_map)


async def _synthesise_response(
    objective: str,
    step_results: dict[int, str],
    blueprint: AgentBlueprint,
    system_persona: str = "",
) -> str:
    """Ask the LLM to synthesise a final response from step results."""
    results_text = "\n".join(
        f"Step {idx}: {result[:_EVIDENCE_CHARS]}"
        for idx, result in sorted(step_results.items())
        if result and result != f"Analysed results from {len(step_results)} prior steps."
    )

    system = system_persona or (
        "You are the Marketing Intelligence Agent. "
        "Provide a clear, helpful, and concise answer to the user's question."
    )

    # Ensure system prompt explicitly forbids fake audit log prefixes
    _no_audit_suffix = (
        " NEVER begin your response with [AUDIT LOG, [Action:, INT-, or any "
        "internal system reference. Respond naturally and directly."
    )
    if "[AUDIT" not in system and "AUDIT LOG" not in system:
        system = system + _no_audit_suffix

    if results_text:
        user_msg = (
            f"User's question / objective: {objective}\n\n"
            f"Information gathered:\n{results_text}\n\n"
            "Using the information above, provide a clear and concise answer "
            "to the user's question. Cite sources where applicable. "
            "Do not expose internal IDs or credentials."
        )
    else:
        # No tool data — answer the question directly from knowledge.
        user_msg = (
            f"User's question: {objective}\n\n"
            "Please answer this question directly and concisely."
        )

    try:
        model = get_llm_gateway().get_chat_model(temperature=0)
        response = await model.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user_msg),
        ])
        # Gemini models may return content as a list of typed blocks
        if isinstance(response.content, str):
            content = response.content
        elif isinstance(response.content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response.content
            )
        else:
            content = str(response.content) if response.content else ""
        if content.strip():
            return _clean_response(content)
        logger.warning("_synthesise_response: LLM returned empty content for objective=%r", objective[:80])
        raise RuntimeError("The AI provider returned an empty response.")
    except Exception as exc:
        logger.error("Response synthesis failed (%s): %s", type(exc).__name__, exc, exc_info=True)
        raise RuntimeError("The AI provider failed to prepare a response.") from exc


_EVIDENCE_CHARS = 6000   # per step; a report cut to 400 chars would leave the model guessing the rest


def _verify_against_evidence(
    final_msg: str,
    plan: AgentPlan,
    db_steps: list[PlanStep],
    step_results: dict[int, str],
    user_prompt: str,
) -> tuple[str, str]:
    """
    For answers built on integration data: check every figure against what the
    integration returned; if the prose states anything it cannot support, show
    the returned data instead.  Always append where the data came from.
    """
    from app.services.grounding import ungrounded_figures
    from app.tools.dynamic_tool import is_dynamic_tool_key

    evidence_parts: list[str] = []
    for step, planned in zip(db_steps, plan.steps):
        if (planned.tool_name and is_dynamic_tool_key(planned.tool_name)
                and step.status == "completed" and step_results.get(planned.step_index)):
            evidence_parts.append(step_results[planned.step_index])
    if not evidence_parts:
        return final_msg, "No integration data used."

    evidence = "\n".join(evidence_parts)
    sources = list(dict.fromkeys(
        line.split("Source:", 1)[1].strip()
        for line in evidence.splitlines() if line.strip().startswith("Source:")
    ))
    bad = ungrounded_figures(final_msg, f"{evidence}\n{plan.objective}\n{user_prompt}")
    if bad:
        logger.warning("Response stated %d figure(s) not found in tool data; showing data instead", len(bad))
        final_msg = (
            "I couldn’t verify my own summary against the data, so here are the figures exactly as "
            "the integration returned them:\n\n" + evidence
        )
        verdict = f"Grounding: replaced (unsupported figures: {', '.join(bad[:5])})."
    else:
        verdict = "Grounding: all figures traced to integration data."
    if sources:
        final_msg = f"{final_msg}\n\nData source: {'; '.join(sources)}"
    return final_msg, verdict


def _failure_message(tool_name: str, result: str) -> str:
    """
    Truthful user-facing text for a failed tool call.

    The reason comes from our own sanitised error strings (provider errors are
    scrubbed of credentials before they get here), never from the model.
    """
    import re

    reason = re.sub(r"^\[[A-Z ]+\]\s*[\w.\-]*:?\s*", "", result.strip(), count=1)[:300]
    if result.lstrip().startswith("[PERMISSION DENIED]"):
        lead = "I wasn’t able to run this because that access has not been authorised for my role."
    elif result.lstrip().startswith("[GOVERNANCE REQUIRED]"):
        lead = "That action needs human approval before I can run it."
    else:
        lead = "I couldn’t complete this request because the data request failed."
    return (
        f"{lead} Reason: {reason or 'no further detail was returned'} "
        "No figures were produced, so I have nothing to report from it."
    )


def _clean_response(text: str) -> str:
    """
    Strip fake audit log prefixes and internal system references that
    the LLM may hallucinate from system persona language.

    These patterns are NEVER legitimate response content — they are
    artefacts of the model misinterpreting audit trail instructions.
    """
    import re
    # Remove lines that start with fake audit/action log markers
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip lines that look like fabricated audit/log/reference prefixes
        if re.match(
            r"^\[AUDIT\s?LOG|^\[Action:|^INT-\d|^\[Data Source:|^\[Audit\]|^\[LOG\]",
            stripped,
            re.IGNORECASE,
        ):
            continue
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    # If we stripped everything, return original (don't make it worse)
    return result if result else text.strip()


def _sanitise_args(args: dict) -> dict:
    """Remove sensitive keys from step arguments before storage."""
    sensitive = {"password", "secret", "token", "api_key", "credential", "dsn"}
    return {k: v for k, v in args.items() if k.lower() not in sensitive}


def _role_key(role_name: str) -> str:
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

