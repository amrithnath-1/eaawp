"""
EAAWP LLM Gateway — administration router.

Provides a single read-only endpoint that returns the gateway's current
configuration health.

Security guarantees:
    • The API key is NEVER included in any response from this router.
    • Only reports api_key_present (boolean) — not the key value.
    • Requires X-Tenant-ID header (consistent with the rest of the API).
    • No endpoint allows model injection or provider override.
    • No endpoint exposes provider credentials.

Available endpoints:
    GET /api/v1/llm/status   — returns LLMStatusResponse (safe metadata only)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import get_current_tenant_id
from app.llm import get_llm_gateway
from app.llm.config import ALLOWED_MODELS, LLMProvider

router = APIRouter(prefix="/api/v1/llm", tags=["llm-gateway"])


# ── Response schema ───────────────────────────────────────────────────────────

class LLMStatusResponse(BaseModel):
    """
    Safe gateway status response.

    Intentionally excludes any credential or secret values.
    Only exposes metadata suitable for an admin dashboard or health check.
    """
    provider: str
    model: str
    api_key_present: bool    # True = key is configured; does NOT confirm validity
    is_ready: bool           # True = all config checks pass (no live API call made)
    error: str | None        # Human-readable reason if is_ready is False
    allowed_models: list[str]  # Application-controlled allowlist (safe to expose)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/status",
    response_model=LLMStatusResponse,
    summary="LLM Gateway configuration status",
    description=(
        "Returns the LLM Gateway's current configuration health. "
        "Does NOT make a live API call to OpenAI — safe to call frequently. "
        "Never returns API key values."
    ),
)
async def get_llm_status(
    tenant_id: str = Depends(get_current_tenant_id),
) -> LLMStatusResponse:
    """
    Return a safe summary of the LLM Gateway configuration.

    Checks performed (no live API call):
        • API key present (non-empty)
        • Default model is in the ALLOWED_MODELS allowlist
        • Provider is registered in the factory

    Does NOT:
        • Return the API key or any portion of it
        • Make a network request to OpenAI
        • Allow model or provider override via this endpoint
    """
    health = get_llm_gateway().health()
    return LLMStatusResponse(
        provider=health.provider,
        model=health.model,
        api_key_present=health.api_key_present,
        is_ready=health.is_ready,
        error=health.error,
        allowed_models=health.allowed_models,
    )
