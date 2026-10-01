"""
EAAWP LLM Gateway — provider factory.

Maps LLMProvider enum values to their concrete BaseLLMProvider
implementations.  This is the only place in the codebase that
knows which class corresponds to which provider string.

To add a new provider (e.g. Anthropic):
    1. Create app/llm/providers/anthropic_provider.py implementing BaseLLMProvider.
    2. Add LLMProvider.ANTHROPIC = "anthropic" to config.LLMProvider.
    3. Add the model allowlist entry in config.ALLOWED_MODELS.
    4. Register it here: _REGISTRY[LLMProvider.ANTHROPIC] = AnthropicProvider()
    5. No other file needs to change.

The factory uses singleton provider instances (one per provider type) because
the providers themselves are stateless — they are just factory objects that
produce configured model instances on demand.
"""

from __future__ import annotations

from app.llm.config import LLMProvider
from app.llm.exceptions import LLMProviderError
from app.llm.providers.openai_provider import OpenAIProvider
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.providers.base import BaseLLMProvider


# ── Provider registry ─────────────────────────────────────────────────────────

_REGISTRY: dict[LLMProvider, BaseLLMProvider] = {
    LLMProvider.OPENAI:  OpenAIProvider(),
    LLMProvider.GOOGLE:  GeminiProvider(),
}


def get_provider(provider: LLMProvider) -> BaseLLMProvider:
    """
    Return the provider implementation for the given LLMProvider enum value.

    Args:
        provider: The LLMProvider to look up.

    Returns:
        The registered BaseLLMProvider instance.

    Raises:
        LLMProviderError: if the provider is not registered.
            (This should only happen during development when a new enum value
             is added to LLMProvider without registering an implementation.)
    """
    impl = _REGISTRY.get(provider)
    if impl is None:
        registered = [p.value for p in _REGISTRY]
        raise LLMProviderError(
            f"No implementation registered for provider '{provider.value}'. "
            f"Registered providers: {registered}. "
            "Add the implementation to app/llm/factory.py."
        )
    return impl
