"""
EAAWP Natural-Language Configuration Interpreter Service

Uses the LLM Gateway (app.llm) to route calls through the centralized
model abstraction. Formerly used ChatOpenAI directly; now uses
get_llm_gateway().get_chat_model_for_role() so model selection is
validated and controlled at the gateway layer.

Security invariants enforced here
-----------------------------------
1. The LLM output is parsed into a strongly-typed ConfigChangePatch.
   Arbitrary text in → structured patch out; no free-form SQL/code.
2. Any tool_key mentioned in schedule/monitoring content is NOT applied
   as a tool scope change — those require the structured form.
3. communication_style is validated against the allowed set.
4. The LLM is instructed (via system prompt) to refuse security-bypass
   requests and return an empty patch with an explanation instead.
5. If the LLM is unavailable, a ServiceUnavailable error is raised and
   NO configuration change is made.

Configuration mode vs execution mode separation
------------------------------------------------
The system prompt explicitly instructs the LLM to ONLY propose config
changes — never to execute business actions (no tool calls, no emails,
no database queries). This is a configuration interpreter, not an agent.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.llm import get_llm_gateway

from app.schemas.config_interpreter import (
    ConfigChangePatch,
    ConfigProposalOut,
    ProposedChangeLine,
)
from app.schemas.role_config import RoleConfigOut

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are the EAAWP Configuration Interpreter for the Digital Marketing Manager role.
Your ONLY job is to convert an administrator's natural-language instruction into a
structured JSON configuration patch.

CRITICAL RULES — read carefully:
1. You are in CONFIGURATION MODE, not execution mode. Never execute business actions.
   Do not call tools, send emails, query databases, or perform any real-world actions.
2. Never bypass security: do not grant unrestricted tool access, do not remove approval
   requirements, do not expose credentials, do not suggest SQL queries.
3. Tool governance changes (enabled/requires_approval/disabled) CANNOT be made via
   natural language. If asked, explain this and leave tool_scopes unchanged.
4. If the request is ambiguous, interpret it conservatively.
5. If the request asks for something unsafe or outside scope, set all lists to empty
   and put a clear explanation in interpreted_intent.

The fields you MAY propose changes to:
- responsibilities_add / responsibilities_remove
- objectives_add / objectives_remove
- instructions_append (appends to existing instructions — do NOT replace them)
- schedule_add (list of {task, frequency} objects — human-readable schedule strings)
- schedule_remove (list of task names to remove)
- monitoring_rules_add (list of {id, name, condition, action} objects)
- monitoring_rules_remove (list of rule IDs to remove)
- quick_prompts_add / quick_prompts_remove
- communication_style (ONLY one of: "Concise", "Formal", "Consultative")

You MUST respond with valid JSON in exactly this structure — no markdown, no backticks,
no explanation outside the JSON:
{
  "interpreted_intent": "One sentence describing what you understood",
  "patch": {
    "responsibilities_add": [],
    "responsibilities_remove": [],
    "objectives_add": [],
    "objectives_remove": [],
    "instructions_append": "",
    "schedule_add": [],
    "schedule_remove": [],
    "monitoring_rules_add": [],
    "monitoring_rules_remove": [],
    "quick_prompts_add": [],
    "quick_prompts_remove": [],
    "communication_style": null
  }
}

Only populate the fields that need changing. Leave others as empty lists / null / "".
"""

_VALID_COMMS_STYLES = {"Concise", "Formal", "Consultative"}


# ── Security validation ───────────────────────────────────────────────────────

def _validate_patch(patch: ConfigChangePatch) -> tuple[list[str], list[str]]:
    """
    Validate a ConfigChangePatch for security and consistency.
    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Validate communication_style
    if patch.communication_style and patch.communication_style not in _VALID_COMMS_STYLES:
        errors.append(
            f"communication_style '{patch.communication_style}' is not valid. "
            f"Must be one of: {sorted(_VALID_COMMS_STYLES)}"
        )

    # Validate schedule_add entries
    for i, sched in enumerate(patch.schedule_add):
        if not isinstance(sched, dict):
            errors.append(f"schedule_add[{i}] must be an object with 'task' and 'frequency'.")
            continue
        if not sched.get("task") or not sched.get("frequency"):
            errors.append(f"schedule_add[{i}] must have non-empty 'task' and 'frequency'.")

    # Validate monitoring_rules_add entries
    for i, rule in enumerate(patch.monitoring_rules_add):
        if not isinstance(rule, dict):
            errors.append(f"monitoring_rules_add[{i}] must be an object.")
            continue
        for field in ("id", "name", "condition", "action"):
            if not rule.get(field):
                errors.append(
                    f"monitoring_rules_add[{i}] missing required field '{field}'."
                )

    # Safety: check for suspicious content in any text field
    dangerous_patterns = [
        r"(?i)(drop\s+table|delete\s+from|truncate|insert\s+into|update\s+\w+\s+set)",
        r"(?i)(exec|execute|eval|subprocess|os\.system)",
        r"(?i)(password|secret|api_key|token|credential)",
        r"(?i)(bypass|unrestricted|unlimited\s+access|disable.*approv)",
    ]
    all_text = " ".join([
        " ".join(patch.responsibilities_add),
        " ".join(patch.responsibilities_remove),
        " ".join(patch.objectives_add),
        " ".join(patch.objectives_remove),
        patch.instructions_append,
        " ".join(patch.quick_prompts_add),
        " ".join(str(s) for s in patch.schedule_add),
        " ".join(str(m) for m in patch.monitoring_rules_add),
    ])
    for pattern in dangerous_patterns:
        if re.search(pattern, all_text):
            errors.append(
                "Proposed changes contain potentially unsafe content and cannot be applied."
            )
            break

    if not any([
        patch.responsibilities_add, patch.responsibilities_remove,
        patch.objectives_add, patch.objectives_remove,
        patch.instructions_append,
        patch.schedule_add, patch.schedule_remove,
        patch.monitoring_rules_add, patch.monitoring_rules_remove,
        patch.quick_prompts_add, patch.quick_prompts_remove,
        patch.communication_style,
    ]):
        warnings.append("No configuration changes were proposed.")

    return errors, warnings


# ── Human-readable diff builder ───────────────────────────────────────────────

def _build_change_lines(patch: ConfigChangePatch) -> list[ProposedChangeLine]:
    lines: list[ProposedChangeLine] = []

    for item in patch.responsibilities_add:
        lines.append(ProposedChangeLine(section="Responsibilities", action="add", description=f"+ {item}"))
    for item in patch.responsibilities_remove:
        lines.append(ProposedChangeLine(section="Responsibilities", action="remove", description=f"− {item}"))

    for item in patch.objectives_add:
        lines.append(ProposedChangeLine(section="Objectives", action="add", description=f"+ {item}"))
    for item in patch.objectives_remove:
        lines.append(ProposedChangeLine(section="Objectives", action="remove", description=f"− {item}"))

    if patch.instructions_append:
        lines.append(ProposedChangeLine(
            section="Instructions", action="add",
            description=f"Append: \"{patch.instructions_append[:120]}{'…' if len(patch.instructions_append) > 120 else ''}\""
        ))

    for sched in patch.schedule_add:
        task = sched.get("task", "?")
        freq = sched.get("frequency", "?")
        lines.append(ProposedChangeLine(section="Schedule", action="add", description=f"+ {task} — {freq}"))
    for task_name in patch.schedule_remove:
        lines.append(ProposedChangeLine(section="Schedule", action="remove", description=f"− {task_name}"))

    for rule in patch.monitoring_rules_add:
        name = rule.get("name", "?")
        condition = rule.get("condition", "?")
        action = rule.get("action", "?")
        lines.append(ProposedChangeLine(
            section="Monitoring Rules", action="add",
            description=f"+ {name}: {condition} → {action}"
        ))
    for rule_id in patch.monitoring_rules_remove:
        lines.append(ProposedChangeLine(section="Monitoring Rules", action="remove", description=f"− rule {rule_id}"))

    for item in patch.quick_prompts_add:
        lines.append(ProposedChangeLine(section="Quick Prompts", action="add", description=f"+ \"{item}\""))
    for item in patch.quick_prompts_remove:
        lines.append(ProposedChangeLine(section="Quick Prompts", action="remove", description=f"− \"{item}\""))

    if patch.communication_style:
        lines.append(ProposedChangeLine(
            section="Communication Style", action="update",
            description=f"Set to: {patch.communication_style}"
        ))

    return lines


# ── Main interpreter ──────────────────────────────────────────────────────────

async def interpret_nl_instruction(
    instruction: str,
    current_config: RoleConfigOut,
    requested_by: str,
    llm_model: str = "gpt-4o-mini",
) -> ConfigProposalOut:
    """
    Use the LLM to interpret a natural-language configuration instruction
    and return a structured proposal (not yet persisted).

    Raises:
        RuntimeError: if the LLM is unavailable or returns unparseable output.
    """
    # Build context about what the current config looks like so the LLM can
    # make sensible add/remove decisions (e.g. avoid adding duplicates).
    config_context = (
        f"Current responsibilities: {json.dumps(current_config.responsibilities)}\n"
        f"Current objectives: {json.dumps(current_config.objectives)}\n"
        f"Current instructions: {current_config.instructions!r}\n"
        f"Current communication_style: {current_config.communication_style!r}\n"
        f"Current schedule tasks: {json.dumps([s.task for s in current_config.schedule_preferences])}\n"
        f"Current monitoring rule IDs: {json.dumps([m.id for m in current_config.monitoring_rules])}\n"
        f"Current quick_prompts: {json.dumps(current_config.quick_prompts)}\n"
    )

    user_message = (
        f"Current role configuration context:\n{config_context}\n"
        f"Administrator instruction: {instruction}"
    )

    try:
        # Route through the LLM Gateway — model validated against ALLOWED_MODELS.
        # The llm_model param comes from the role's RoleConfiguration.llm_model,
        # which is already validated by RoleConfigUpdate.validate_llm_model.
        # Gateway validation is a second, independent guard.
        llm = get_llm_gateway().get_chat_model_for_role(
            role_llm_model=llm_model,
            temperature=0,
        )
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
    except Exception as exc:
        logger.error("LLM unavailable during config interpretation: %s", exc)
        raise RuntimeError(
            "The language model is temporarily unavailable. "
            "Your configuration has not been changed. Please try again shortly."
        ) from exc

    # Parse the JSON response
    raw_text: str = ""
    if isinstance(response.content, str):
        raw_text = response.content.strip()
    elif isinstance(response.content, list):
        parts = [
            block.get("text", "")
            for block in response.content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        raw_text = " ".join(parts).strip()

    # Strip any accidental markdown fences
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned non-JSON for config interpretation: %r", raw_text[:300])
        raise RuntimeError(
            "The language model returned an unrecognised response format. "
            "Your configuration has not been changed."
        ) from exc

    interpreted_intent = str(parsed.get("interpreted_intent", ""))
    patch_dict = parsed.get("patch", {})

    try:
        patch = ConfigChangePatch(**patch_dict)
    except (ValidationError, TypeError) as exc:
        logger.error("ConfigChangePatch validation failed: %s", exc)
        raise RuntimeError(
            "The proposed configuration change could not be validated. "
            "Your configuration has not been changed."
        ) from exc

    errors, warnings = _validate_patch(patch)
    change_lines = _build_change_lines(patch)

    return ConfigProposalOut(
        id=str(uuid.uuid4()),
        role_key=current_config.role_key,
        tenant_id=current_config.tenant_id,
        original_instruction=instruction,
        interpreted_intent=interpreted_intent,
        proposed_changes=change_lines,
        patch=patch,
        validation_errors=errors,
        validation_warnings=warnings,
        approval_status="pending",
        created_at=datetime.now(timezone.utc),
        approved_at=None,
        approved_by=None,
    )


# ── Apply patch to a RoleConfigUpdate ─────────────────────────────────────────

def apply_patch_to_config(
    patch: ConfigChangePatch,
    current: RoleConfigOut,
) -> dict:
    """
    Apply a ConfigChangePatch to the current role config and return a dict
    suitable for passing to the existing PATCH /api/v1/roles/{role_key} endpoint.

    Only the changed fields are included — unaffected fields are omitted so
    the existing partial-update logic merges correctly.
    """
    update: dict = {}

    # Responsibilities
    if patch.responsibilities_add or patch.responsibilities_remove:
        responsibilities = list(current.responsibilities)
        for item in patch.responsibilities_add:
            if item not in responsibilities:
                responsibilities.append(item)
        if patch.responsibilities_remove:
            responsibilities = [
                r for r in responsibilities
                if not any(rem.lower() in r.lower() for rem in patch.responsibilities_remove)
            ]
        update["responsibilities"] = responsibilities

    # Objectives
    if patch.objectives_add or patch.objectives_remove:
        objectives = list(current.objectives)
        for item in patch.objectives_add:
            if item not in objectives:
                objectives.append(item)
        if patch.objectives_remove:
            objectives = [
                o for o in objectives
                if not any(rem.lower() in o.lower() for rem in patch.objectives_remove)
            ]
        update["objectives"] = objectives

    # Instructions (append only — never replace)
    if patch.instructions_append:
        sep = " " if current.instructions and not current.instructions.endswith(".") else ""
        update["instructions"] = (current.instructions + sep + patch.instructions_append).strip()

    # Schedule preferences
    if patch.schedule_add or patch.schedule_remove:
        schedules = [s.model_dump() for s in current.schedule_preferences]
        for new_sched in patch.schedule_add:
            # Avoid duplicates by task name
            existing_tasks = {s["task"].lower() for s in schedules}
            task = new_sched.get("task", "")
            if task.lower() not in existing_tasks:
                schedules.append({
                    "task": task,
                    "frequency": new_sched.get("frequency", ""),
                    "enabled": True,
                })
        if patch.schedule_remove:
            schedules = [
                s for s in schedules
                if s["task"] not in patch.schedule_remove
            ]
        update["schedule_preferences"] = schedules

    # Monitoring rules
    if patch.monitoring_rules_add or patch.monitoring_rules_remove:
        rules = [m.model_dump() for m in current.monitoring_rules]
        existing_ids = {r["id"] for r in rules}
        for new_rule in patch.monitoring_rules_add:
            rule_id = new_rule.get("id", "")
            if rule_id not in existing_ids:
                rules.append({
                    "id": rule_id,
                    "name": new_rule.get("name", ""),
                    "condition": new_rule.get("condition", ""),
                    "action": new_rule.get("action", ""),
                    "enabled": True,
                })
        if patch.monitoring_rules_remove:
            rules = [r for r in rules if r["id"] not in patch.monitoring_rules_remove]
        update["monitoring_rules"] = rules

    # Quick prompts
    if patch.quick_prompts_add or patch.quick_prompts_remove:
        prompts = list(current.quick_prompts)
        for item in patch.quick_prompts_add:
            if item not in prompts:
                prompts.append(item)
        if patch.quick_prompts_remove:
            prompts = [p for p in prompts if p not in patch.quick_prompts_remove]
        update["quick_prompts"] = prompts

    # Communication style
    if patch.communication_style:
        update["communication_style"] = patch.communication_style

    return update
