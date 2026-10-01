"""
EAAWP LLM Gateway — domain exceptions.

All LLM-layer errors inherit from LLMGatewayError so callers can catch
at whatever granularity they need.
"""

from __future__ import annotations


class LLMGatewayError(Exception):
    """Base class for all LLM Gateway errors."""


class LLMConfigurationError(LLMGatewayError):
    """
    Raised when the gateway cannot be configured from the current settings.

    Examples:
        - OPENAI_API_KEY is missing or empty.
        - No default model is defined in settings.
        - A required configuration field is invalid.

    This is a startup / configuration problem, not a runtime API error.
    It should never be surfaced to end users; log it and fail fast at
    application startup or when the gateway is first requested.
    """


class LLMUnsupportedModelError(LLMGatewayError):
    """
    Raised when a caller requests a provider/model combination that is not
    in the application-controlled allowlist.

    This guards against arbitrary model injection from frontend payloads,
    role configuration edits, or any other external input.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            f"Model '{model}' is not an approved model for provider '{provider}'. "
            "Update ALLOWED_MODELS in LLMConfig to add it."
        )
        self.provider = provider
        self.model = model


class LLMProviderError(LLMGatewayError):
    """
    Raised when a provider implementation encounters a runtime error that
    is specific to the provider (e.g. authentication failure, rate limit,
    network timeout).

    The underlying provider exception is always chained via `raise ... from exc`
    so the original traceback is preserved for diagnostics without leaking
    credential values into the error message.
    """
