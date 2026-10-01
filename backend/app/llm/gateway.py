"""
EAAWP LLM Gateway — the single controlled entry point for LLM usage.

Architecture
────────────
Application components
        ↓
   LLMGateway            ← this file
        ↓
   ProviderFactory       ← factory.py
        ↓
   OpenAIProvider        ← providers/openai_provider.py
        ↓
   ChatOpenAI (LangChain)
        ↓
   OpenAI API

Usage
─────
    # Standard pattern (uses app settings):
    from app.llm import get_llm_gateway
    gateway = get_llm_gateway()
    model = gateway.get_chat_model()               # default model, temp=0
    model = gateway.get_chat_model(temperature=0.7)  # content generation
    model = gateway.get_chat_model(model="gpt-4o")   # specific model

    # Role-aware pattern (respects role's llm_model, still validated):
    model = gateway.get_chat_model_for_role(role_llm_model="gpt-4o")

    # With tool binding (engine pattern):
    model = gateway.get_chat_model()
    bound = model.bind_tools(tools)

Security
────────
    • api_key never appears in logs, error messages, or returned objects.
    • model and provider are validated before any network call.
    • LLMConfig is immutable after construction.
    • The gateway instance is a lazy singleton — created once, shared across
      requests; the provider factory produces fresh model instances per call.

Health check
────────────
    status = gateway.health()  # → LLMHealthStatus
    # Returns: provider, model, api_key_present, is_ready, error (if any)
    # Does NOT make a live API call — safe to call at startup or in a
    # lightweight readiness endpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.llm.config import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    LLMConfig,
    LLMProvider,
    llm_config_from_settings,
)
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMUnsupportedModelError,
)
from app.llm.factory import get_provider

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


# ── Health status ──────────────────────────────────────────────────────────────

@dataclass
class LLMHealthStatus:
    """
    Safe summary of gateway readiness.

    api_key_present: True if a key is configured — does NOT mean the key is valid.
    is_ready:        True if all configuration checks pass.
    error:           Human-readable error description if is_ready is False.

    NEVER includes the actual api_key value.
    """
    provider: str
    model: str
    api_key_present: bool
    is_ready: bool
    error: str | None = None
    allowed_models: list[str] = field(default_factory=list)


# ── Gateway ────────────────────────────────────────────────────────────────────

class LLMGateway:
    """
    Central LLM access point for all EAAWP application components.

    Instantiated once (singleton via get_llm_gateway()).  All request-level
    LLM clients are produced by calling get_chat_model() — each call returns
    a fresh configured model instance, which is the existing behaviour across
    all prior call sites.
    """

    def __init__(self) -> None:
        # Attempt to build the default config at gateway creation time so
        # configuration errors surface immediately at startup rather than
        # on the first user request.
        self._default_config: LLMConfig | None = None
        self._init_error: str | None = None

        try:
            self._default_config = llm_config_from_settings()
            logger.info(
                "LLM Gateway initialised — provider=%s model=%s",
                self._default_config.provider.value,
                self._default_config.model,
            )
        except LLMConfigurationError as exc:
            # Record but don't raise — allows the app to start in degraded mode
            # so health endpoints remain reachable.  Any actual LLM call will
            # still fail with a clear error.
            self._init_error = str(exc)
            logger.warning("LLM Gateway: configuration error at startup — %s", exc)

    # ── Core factory ──────────────────────────────────────────────────────────

    def get_chat_model(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> "BaseChatModel":
        """
        Return a configured, ready-to-use LangChain chat model.

        Supports:
            • .ainvoke(messages)     — all existing async paths
            • .invoke(messages)      — sync paths
            • .bind_tools(tools)     — DynamicAgentEngine tool binding

        Args:
            model:       Model name override.  Must be in ALLOWED_MODELS.
            temperature: Temperature override.  Default is 0.0 (deterministic).
            max_tokens:  Optional token cap.
            timeout:     Optional timeout override in seconds.

        Raises:
            LLMConfigurationError:    if no API key is configured.
            LLMUnsupportedModelError: if the requested model is not allowed.
            LLMProviderError:         if the provider fails to initialise.
        """
        config = llm_config_from_settings(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return self._build_model(config)

    def get_chat_model_for_role(
        self,
        role_llm_model: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> "BaseChatModel":
        """
        Return a chat model respecting a role's configured llm_model.

        The role's model is validated against ALLOWED_MODELS before use —
        no arbitrary model injection is possible even if the role's
        stored value is somehow out of date.

        Falls back to DEFAULT_MODEL if role_llm_model is None or empty.

        Args:
            role_llm_model: The llm_model from RoleConfiguration (may be None).
            temperature:    Temperature override.
            max_tokens:     Optional token cap.
            timeout:        Optional timeout override.

        Raises:
            LLMConfigurationError:    if no API key is configured.
            LLMUnsupportedModelError: if the role's model is not in the allowlist.
        """
        from app.llm.config import _get_default_model
        resolved_model = role_llm_model if role_llm_model else _get_default_model()
        return self.get_chat_model(
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def get_chat_model_from_config(self, config: LLMConfig) -> "BaseChatModel":
        """
        Return a chat model from a pre-built LLMConfig.

        Use this when the caller has already constructed a validated config
        (e.g. in tests or specialised service layers).

        Args:
            config: A validated LLMConfig instance.

        Raises:
            LLMProviderError: if the provider fails to initialise.
        """
        return self._build_model(config)

    # ── Health check ──────────────────────────────────────────────────────────

    def health(self) -> LLMHealthStatus:
        """
        Return the gateway's configuration health without making any API call.

        Checks:
            • API key is present (non-empty)
            • Default model is in the allowlist
            • Provider is registered

        Does NOT validate that the API key is actually accepted by OpenAI —
        that would require a network call, which is intentionally avoided here.
        Use a separate explicit connectivity test if needed.
        """
        from app.llm.config import ALLOWED_MODELS
        from app.llm.factory import _REGISTRY

        if self._init_error:
            return LLMHealthStatus(
                provider=LLMProvider.OPENAI.value,
                model=DEFAULT_MODEL,
                api_key_present=False,
                is_ready=False,
                error=self._init_error,
                allowed_models=sorted(ALLOWED_MODELS.get(LLMProvider.OPENAI, frozenset())),
            )

        assert self._default_config is not None  # guaranteed by __init__ path above

        provider_registered = self._default_config.provider in _REGISTRY

        is_ready = (
            self._default_config.has_api_key()
            and provider_registered
        )

        return LLMHealthStatus(
            provider=self._default_config.provider.value,
            model=self._default_config.model,
            api_key_present=self._default_config.has_api_key(),
            is_ready=is_ready,
            error=None if is_ready else "Provider not registered or API key missing.",
            allowed_models=sorted(
                ALLOWED_MODELS.get(self._default_config.provider, frozenset())
            ),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_model(self, config: LLMConfig) -> "BaseChatModel":
        """Dispatch to the registered provider and return the model instance."""
        provider_impl = get_provider(config.provider)
        return provider_impl.get_chat_model(config)


# ── Application-level singleton ───────────────────────────────────────────────
#
# Lazy singleton — created once on first call, then reused.
# Thread-safe in Python's GIL for simple assignment.

_gateway_instance: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    """
    Return the application's LLMGateway singleton.

    Safe to call repeatedly — the same instance is returned each time.
    This matches the existing pattern where Settings is a module-level
    singleton (settings = Settings()).
    """
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = LLMGateway()
    return _gateway_instance
