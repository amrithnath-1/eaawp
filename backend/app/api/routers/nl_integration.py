"""
EAAWP Phase B — Natural Language Integration Manager Router

POST /api/v1/nl-integration/chat    — stateful NL integration conversation
POST /api/v1/nl-integration/parse   — one-shot intent parsing (no action taken)

Security model:
- The LLM proposes intent — the backend validates and acts.
- No credential, token, or secret ever passes through this router to the LLM.
- All actions (connect/disconnect/grant) still require proper authorization.
- Tenant_id is derived from the auth token — never from the request body.
- Missing LLM → 503, not 500 (known failure mode, not a crash).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant_id, get_optional_tenant_id
from app.db.session import get_db
from app.integrations import manager as mgr
from app.integrations.integration_registry import integration_registry
from app.schemas.nl_integration import (
    IntegrationConversationRequest,
    IntegrationConversationResponse,
    NLIntegrationRequest,
    IntegrationIntent,
)
from app.services.nl_integration_service import (
    build_conversation_reply,
    parse_integration_intent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nl-integration", tags=["nl-integration"])


@router.post(
    "/parse",
    response_model=IntegrationIntent,
    summary="Parse a natural-language integration instruction into a structured intent",
    description=(
        "Uses the LLM to classify what the user wants to do with integrations. "
        "Returns a structured intent — never takes any action. "
        "The backend validates all fields before any action is taken."
    ),
)
async def parse_intent(
    body: NLIntegrationRequest,
    tenant_id: str = Depends(get_optional_tenant_id),
) -> IntegrationIntent:
    """
    Parse a natural-language string into a structured IntegrationIntent.
    No side effects — read-only intent classification.
    """
    try:
        intent = await parse_integration_intent(
            instruction=body.instruction,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM unavailable: {exc}",
        ) from exc

    return intent


@router.post(
    "/chat",
    response_model=IntegrationConversationResponse,
    summary="Natural-language integration setup conversation",
    description=(
        "Stateful conversational interface for setting up integrations. "
        "The assistant understands what integration you want to set up, explains "
        "requirements, and guides you through the connection flow. "
        "All sensitive operations (OAuth, credential storage) are handled separately "
        "by the backend — never through this chat interface."
    ),
)
async def chat(
    body: IntegrationConversationRequest,
    tenant_id: str = Depends(get_optional_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> IntegrationConversationResponse:
    """
    Handle one turn of the integration setup conversation.

    1. Parse the user's message into a structured intent via LLM.
    2. Load current integration state for the tenant.
    3. Build a contextual reply based on intent + state.
    4. Return reply + next_action hint for the frontend.

    The LLM never has access to credentials or tenant data — only the
    integration catalogue (public metadata) and provider list.
    """
    # Parse intent
    try:
        intent = await parse_integration_intent(
            instruction=body.message,
        )
    except RuntimeError as exc:
        logger.warning("NL integration chat LLM unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Integration assistant is unavailable because the configured AI model request failed. Check model configuration and connectivity, then retry.",
        ) from exc

    # Load current integrations for context (safe metadata only, no credentials)
    try:
        integrations = await mgr.list_integrations(tenant_id=tenant_id, db=db)
        tenant_integrations = [
            {
                "id": i.id,
                "provider_type": i.provider_type,
                "display_name": i.display_name,
                "status": i.status,
                "is_enabled": i.is_enabled,
                "last_tested_at": i.last_tested_at.isoformat() if i.last_tested_at else None,
            }
            for i in integrations
        ]
    except Exception as exc:
        logger.warning("Failed to load integrations for NL chat: %s", exc)
        tenant_integrations = []

    # Build reply and next action
    reply, next_action, action_data = await build_conversation_reply(
        intent, tenant_integrations, db=db, tenant_id=tenant_id
    )

    # Build available providers list (public catalogue, no credentials)
    available_providers = [
        {
            "provider_type": p["provider_type"],
            "display_name": p["display_name"],
            "description": p["description"],
        }
        for p in integration_registry.provider_catalogue()
    ]

    conversation_id = body.conversation_id or str(uuid.uuid4())

    return IntegrationConversationResponse(
        conversation_id=conversation_id,
        reply=reply,
        intent=intent,
        next_action=next_action,  # type: ignore[arg-type]
        action_data=action_data,
        available_providers=available_providers,
    )
