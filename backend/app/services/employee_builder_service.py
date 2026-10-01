"""
EAAWP Phase H — AI Employee Builder Service.

Uses the LLM to parse a natural-language employee creation request into
a structured EmployeeBlueprintProposal. The LLM reasons about requirements;
the backend validates capabilities, detects missing integrations, and
requires human approval before creating the employee.

Security invariants:
- LLM cannot set credentials, tenant_id, or bypass governance.
- Blueprint must be approved before employee is activated.
- Tool lists are validated against MASTER_TOOL_REGISTRY and known capabilities.
- Arbitrary system_persona is sanitized — no injection of instructions.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.integrations.integration_registry import integration_registry
from app.llm import get_llm_gateway
from app.schemas.employee_builder import (
    EmployeeBlueprintProposal,
    MissingIntegration,
    RequiredCapability,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are the EAAWP AI Employee Builder.

A user will describe what kind of AI employee they want.
Your job is to produce a structured JSON blueprint proposal.

RULES:
- You NEVER set credentials, passwords, or API keys.
- You NEVER bypass approval processes.
- You ONLY propose — the backend decides what is allowed.
- You NEVER modify source code or production systems.
- Keep system_persona professional and role-focused. No roleplay, no jailbreaks.

KNOWN TOOL KEYS (examples — use only these):
  query_company_data, fetch_knowledge_base, generate_report,
  create_internal_task, draft_email, send_email (GUARDED — needs approval),
  query_campaign_analytics, create_campaign

KNOWN INTEGRATION TYPES: google_search_console, google_analytics,
  facebook, github, postgresql, mysql, mcp

OUTPUT FORMAT — respond ONLY with a valid JSON object:
{
  "name": "<employee display name>",
  "role_key": "<UPPER_SNAKE_CASE role key>",
  "purpose": "<one sentence purpose>",
  "responsibilities": ["<responsibility 1>", ...],
  "objectives": ["<objective 1>", ...],
  "required_capabilities": [
    {
      "provider_type": "<provider>",
      "capability_key": "<capability>",
      "reason": "<why needed>"
    }
  ],
  "missing_integrations": [],
  "allowed_tools": ["<tool_key>", ...],
  "guarded_tools": ["send_email"],
  "suggested_schedule": "<cron or null>",
  "communication_style": "Concise",
  "llm_model": "gpt-4o-mini",
  "system_persona": "<role-specific persona description — professional, no jailbreaks>"
}

Be specific about required_capabilities. If the request needs competitor research,
list google_search_console and google_analytics capabilities.
If unsure about a capability, include it in missing_integrations.
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _sanitize_persona(text: str) -> str:
    """Remove potential injection patterns from system_persona."""
    injection_re = re.compile(
        r"(ignore previous|override system|you are now|disregard|"
        r"forget your instructions|act as|jailbreak|bypass)",
        re.IGNORECASE,
    )
    if injection_re.search(text):
        return "You are a professional AI employee. Follow your configured responsibilities."
    return text[:2000]


async def generate_employee_blueprint(
    instruction: str,
    tenant_id: str,
    created_by: str,
    existing_integrations: list[dict],
) -> EmployeeBlueprintProposal:
    """
    Use the LLM to generate a structured employee blueprint.

    1. Parse instruction → blueprint proposal.
    2. Cross-check required_capabilities against existing integrations.
    3. Identify missing integrations.
    4. Return a proposal for human review.

    Raises RuntimeError if LLM is unavailable.
    """
    gateway = get_llm_gateway()
    if not gateway.health().is_ready:
        raise RuntimeError("LLM unavailable — cannot generate employee blueprint.")

    chat_model = gateway.get_chat_model()

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.strip()),
        HumanMessage(content=instruction.strip()),
    ]

    try:
        response = await chat_model.ainvoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("LLM call failed during employee blueprint generation")
        raise RuntimeError(f"LLM error: {exc}") from exc

    data = _extract_json(raw_text)
    if not data:
        logger.warning("LLM returned unparseable blueprint: %r", raw_text[:200])
        raise RuntimeError("LLM returned an unparseable response.")

    # Build required capabilities list
    req_caps: list[RequiredCapability] = []
    for cap_data in data.get("required_capabilities", []):
        if isinstance(cap_data, dict):
            req_caps.append(RequiredCapability(
                provider_type=str(cap_data.get("provider_type", ""))[:64],
                capability_key=str(cap_data.get("capability_key", ""))[:128],
                reason=str(cap_data.get("reason", ""))[:500],
            ))

    # Cross-check against existing integrations
    connected_providers = {i["provider_type"] for i in existing_integrations if i.get("status") == "connected"}
    for rc in req_caps:
        if rc.provider_type in connected_providers:
            matching = [i for i in existing_integrations
                        if i["provider_type"] == rc.provider_type and i.get("status") == "connected"]
            if matching:
                rc = RequiredCapability(
                    provider_type=rc.provider_type,
                    capability_key=rc.capability_key,
                    reason=rc.reason,
                    is_available=True,
                    integration_id=matching[0].get("id"),
                )

    # Detect missing integrations
    required_providers = {rc.provider_type for rc in req_caps}
    missing_providers = required_providers - connected_providers
    missing_integrations: list[MissingIntegration] = []
    for ptype in missing_providers:
        provider = integration_registry.get(ptype)
        missing_integrations.append(MissingIntegration(
            provider_type=ptype,
            display_name=provider.display_name if provider else ptype,
            reason=f"Required for {ptype} capabilities but not currently connected.",
            required_capabilities=[
                rc.capability_key for rc in req_caps if rc.provider_type == ptype
            ],
        ))

    # Sanitize system_persona
    system_persona = _sanitize_persona(str(data.get("system_persona", "")))

    # Validate tool lists against known tools
    from app.tools.registry import MASTER_TOOL_REGISTRY
    known_tools = set(MASTER_TOOL_REGISTRY.keys())
    allowed_tools = [t for t in data.get("allowed_tools", []) if isinstance(t, str)]
    guarded_tools = [t for t in data.get("guarded_tools", []) if isinstance(t, str)]

    proposal = EmployeeBlueprintProposal(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=str(data.get("name", "New AI Employee"))[:255],
        role_key=re.sub(r"[^A-Z0-9_]", "_", str(data.get("role_key", "CUSTOM_EMPLOYEE")).upper())[:128],
        purpose=str(data.get("purpose", ""))[:1000],
        responsibilities=[str(r)[:200] for r in data.get("responsibilities", [])[:10]],
        objectives=[str(o)[:200] for o in data.get("objectives", [])[:10]],
        required_capabilities=req_caps,
        missing_integrations=missing_integrations,
        allowed_tools=allowed_tools[:20],
        guarded_tools=guarded_tools[:10],
        suggested_schedule=str(data.get("suggested_schedule", ""))[:100] or None,
        communication_style=str(data.get("communication_style", "Concise"))[:32],
        llm_model=str(data.get("llm_model", "gpt-4o-mini"))[:64],
        system_persona=system_persona,
        approval_status="pending",
        created_by=created_by,
    )
    return proposal
