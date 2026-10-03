"""
EAAWP Phase B - Natural Language Integration Service

Parses natural-language instructions about integrations using the LLM Gateway.
The LLM produces a structured IntegrationIntent - it never directly executes
OAuth, modifies credentials, or accesses external APIs.

Security invariants:
- The LLM produces proposals only. The backend router validates and acts.
- Provider type is validated against KNOWN_PROVIDERS before any action.
- The LLM cannot supply credentials, tenant_id, or grant permissions directly.
- System prompt instructs the LLM to refuse credential extraction requests.
- If the LLM is unavailable, raise RuntimeError so the caller can return 503.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.integrations.integration_registry import integration_registry
from app.llm import get_llm_gateway
from app.schemas.nl_integration import (
    KNOWN_PROVIDERS,
    IntegrationIntent,
    IntegrationConversationResponse,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are the EAAWP Integration Setup Assistant.

Your job is to understand what integration a user wants to set up, and produce a
structured JSON response describing their intent.

RULES:
- You NEVER ask for passwords, API keys, OAuth tokens, or any credentials.
- You NEVER attempt to connect to any external service yourself.
- You NEVER claim an integration is connected unless the backend confirms it.
- You REFUSE requests to bypass permissions or access other tenants' data.
- You ONLY classify intent -- the backend does the actual work.

KNOWN PROVIDERS:
- google_search_console -> Google Search Console (website search analytics)
- google_analytics -> Google Analytics (website traffic and conversions)
- facebook -> Meta / Facebook (page insights, ad campaign metrics)
- github -> GitHub (repositories, issues, pull requests)
- postgresql -> PostgreSQL database
- mysql -> MySQL / MariaDB database
- mcp -> MCP (Model Context Protocol) server

OUTPUT FORMAT -- respond ONLY with a JSON object:
{
  "intent_type": "CONNECT_INTEGRATION" | "DISCONNECT_INTEGRATION" | "LIST_INTEGRATIONS" | "LIST_CAPABILITIES" | "GRANT_CAPABILITY" | "REVOKE_CAPABILITY" | "CHECK_STATUS" | "TEST_CONNECTION" | "UNKNOWN",
  "provider_type": "<canonical_type_or_null>",
  "requested_capabilities": [],
  "target_role_key": "<role_key_or_null>",
  "display_name": "<human_name_or_null>",
  "reasoning": "<brief_reasoning>",
  "confidence": 0.0..1.0,
  "missing_information": ["<things_needed_before_proceeding>"]
}

EXAMPLES:
User: "Connect Google Search Console"
-> intent_type: CONNECT_INTEGRATION, provider_type: google_search_console, confidence: 0.95

User: "Give the marketing employee access to search analytics"
-> intent_type: GRANT_CAPABILITY, provider_type: google_search_console,
  requested_capabilities: ["get_search_analytics"],
  target_role_key: DIGITAL_MARKETING_MANAGER, confidence: 0.85

User: "What integrations are connected?"
-> intent_type: LIST_INTEGRATIONS, provider_type: null, confidence: 0.99

Respond ONLY with a valid JSON object. No markdown, no explanation, no surrounding text.
"""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling potential markdown wrapping."""
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


async def parse_integration_intent(
    instruction: str,
    llm_model: str | None = None,
) -> IntegrationIntent:
    """
    Use the LLM to parse a natural-language integration instruction into
    a structured IntegrationIntent.

    Raises RuntimeError if the LLM is unavailable or produces invalid output.
    """
    gateway = get_llm_gateway()
    if not gateway.health().is_ready:
        raise RuntimeError(
            "LLM is not available. Integration intent parsing requires a configured LLM."
        )

    # Use the configured provider/model unless a role explicitly overrides it.
    # A hard-coded OpenAI model bypasses a Gemini-only deployment's configuration.
    chat_model = (
        gateway.get_chat_model_for_role(role_llm_model=llm_model)
        if llm_model
        else gateway.get_chat_model(temperature=0)
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.strip()),
        HumanMessage(content=instruction.strip()),
    ]

    try:
        response = await chat_model.ainvoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.exception("LLM call failed during integration intent parsing")
        raise RuntimeError(f"LLM unavailable: {exc}") from exc

    data = _extract_json(raw_text)
    if not data:
        logger.warning("LLM returned unparseable response for intent: %r", raw_text[:200])
        return IntegrationIntent(
            intent_type="UNKNOWN",
            reasoning="Could not parse LLM response",
            confidence=0.0,
        )

    try:
        intent = IntegrationIntent(**data)
    except Exception as exc:
        logger.warning("IntegrationIntent validation failed: %s -- data: %s", exc, data)
        return IntegrationIntent(
            intent_type="UNKNOWN",
            reasoning=f"Parse error: {exc}",
            confidence=0.0,
        )

    return intent


def build_conversation_reply(
    intent: IntegrationIntent,
    tenant_integrations: list[dict],
) -> tuple[str, str, dict]:
    """
    Build a natural-language reply and determine next_action based on intent.
    Returns: (reply_text, next_action, action_data)
    The reply never contains credentials, tokens, or sensitive data.
    """
    provider = intent.provider_type
    provider_info = next(
        (p for p in integration_registry.provider_catalogue() if p["provider_type"] == provider),
        None,
    ) if provider else None

    existing = [i for i in tenant_integrations if i.get("provider_type") == provider]

    if intent.intent_type == "UNKNOWN":
        supported = ", ".join(
            p["display_name"] for p in integration_registry.provider_catalogue()
        )
        return (
            "I couldn’t match that request to a supported integration or action. "
            f"Currently available providers are: {supported}. "
            "Tell me which one you want to connect, or choose it from the tabs below.",
            "CLARIFY",
            {},
        )

    if intent.intent_type == "LIST_INTEGRATIONS":
        if not tenant_integrations:
            return (
                "No integrations are currently connected. "
                "You can connect Google Search Console, Google Analytics, "
                "Facebook, GitHub, or a database to give your AI employees "
                "access to real data.",
                "NONE",
                {},
            )
        lines = [
            "- {} ({}) - {}".format(i["display_name"], i["provider_type"], i["status"])
            for i in tenant_integrations
        ]
        return ("Connected integrations:\n" + "\n".join(lines), "NONE", {})

    if intent.intent_type == "CONNECT_INTEGRATION":
        if not provider:
            known = ", ".join(sorted(KNOWN_PROVIDERS))
            return (
                "Which integration would you like to connect? Supported: {}.".format(known),
                "CLARIFY",
                {},
            )
        if existing and existing[0].get("status") == "connected":
            pname = provider_info["display_name"] if provider_info else provider
            return (
                "{} is already connected. Would you like to test the connection, "
                "view its capabilities, or grant access to an employee?".format(pname),
                "SHOW_STATUS",
                {"integration_id": existing[0]["id"]},
            )
        if provider in ("google_search_console", "google_analytics"):
            pname = provider_info["display_name"] if provider_info else provider
            return (
                "To connect {}, you will need to authorize access via their OAuth screen. "
                "Click the Connect button to begin. "
                "Only the minimum required read-only permissions will be requested.".format(pname),
                "REDIRECT_TO_OAUTH",
                {"provider_type": provider},
            )
        if provider == "github":
            return (
                "Use the GitHub tab to enter a least-privilege personal access token in the secure connection form. "
                "EAAWP will save it encrypted and test access; the assistant chat will not receive the token.",
                "OPEN_GITHUB_FORM",
                {"provider_type": provider},
            )
        if provider == "mcp":
            return (
                "Use the MCP Server tab to enter the HTTP server URL and optional authentication details in the secure form. "
                "EAAWP will test access and discover tools; you must grant tools to an AI role before it can use them.",
                "OPEN_MCP_FORM",
                {"provider_type": provider},
            )
        else:
            pname = provider_info["display_name"] if provider_info else provider
            return (
                "{} is listed in the provider catalogue, but a complete in-app setup flow is not available yet. "
                "It has not been connected. Use a supported connection flow or ask your administrator to enable this provider.".format(pname),
                "UNAVAILABLE",
                {"provider_type": provider},
            )

    if intent.intent_type == "LIST_CAPABILITIES":
        if not provider or not provider_info:
            return (
                "Which integration's capabilities would you like to see? "
                "For example: 'What can Google Search Console do?'",
                "CLARIFY",
                {},
            )
        caps = provider_info.get("capabilities", [])
        lines = ["- {}: {}".format(c["display_name"], c["description"]) for c in caps]
        pname = provider_info["display_name"]
        return (
            "{} capabilities:\n".format(pname) + "\n".join(lines) +
            "\n\nAll capabilities require an explicit grant before an AI employee can use them.",
            "SHOW_CAPABILITIES",
            {"provider_type": provider, "capabilities": caps},
        )

    if intent.intent_type == "GRANT_CAPABILITY":
        if not provider or not intent.target_role_key:
            missing = []
            if not provider:
                missing.append("which integration")
            if not intent.target_role_key:
                missing.append("which AI employee")
            return (
                "To grant a capability, I need to know {}. "
                "For example: 'Give the Digital Marketing Manager access to "
                "Search Console analytics'.".format(" and ".join(missing)),
                "CLARIFY",
                {},
            )
        caps = intent.requested_capabilities or ["all capabilities"]
        pname = provider_info["display_name"] if provider_info else provider
        return (
            "I would like to grant {} from {} to {}. "
            "Confirm to proceed - this will allow the employee to use these capabilities.".format(
                ", ".join(caps), pname, intent.target_role_key
            ),
            "CONFIRM_GRANT",
            {
                "provider_type": provider,
                "role_key": intent.target_role_key,
                "capabilities": intent.requested_capabilities,
            },
        )

    if intent.intent_type == "CHECK_STATUS":
        if not existing:
            pname = provider_info["display_name"] if provider_info else (provider or "that integration")
            return (
                "{} is not currently connected. Would you like to connect it?".format(pname),
                "NONE",
                {},
            )
        i = existing[0]
        return (
            "{} status: {}. Last tested: {}.".format(
                i["display_name"], i["status"].upper(),
                i.get("last_tested_at") or "never"
            ),
            "SHOW_STATUS",
            {"integration_id": i["id"]},
        )

    # Fallback
    return (
        "I understand you would like to work with integrations. "
        "Could you be more specific? For example: 'Connect Google Analytics' or "
        "'Show me what Search Console can do'.",
        "CLARIFY",
        {},
    )
