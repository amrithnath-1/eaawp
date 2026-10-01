"""
EAAWP LLM Gateway — configuration and allowlist.

LLMProvider
    Enum of supported providers.  Adding a new value here is the first step
    in adding a new provider — the provider implementation comes second.

LLMConfig
    Validated, immutable configuration object passed to the provider factory.

    Key security guarantees:
    ─────────────────────────
    • api_key is stored as a private attribute and never appears in repr(),
      str(), or dict() output so it cannot accidentally leak into logs or
      serialised API responses.
    • model and provider are validated against ALLOWED_MODELS at construction
      time.  An invalid combination raises LLMUnsupportedModelError
      immediately — before any network call is made.
    • temperature is clamped to [0.0, 2.0] per the OpenAI spec.

    ALLOWED_MODELS
    ──────────────
    This is the application-controlled allowlist.  It MUST be changed here
    (server-side) to allow additional models.  Frontend / tenant payloads
    that name a model not on this list are rejected.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.llm.exceptions import LLMConfigurationError, LLMUnsupportedModelError


# ── Provider enum ─────────────────────────────────────────────────────────────

class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    GOOGLE = "google"    # Google Gemini via Gemini API (langchain_google_genai)


# ── Application-controlled model allowlist ────────────────────────────────────
#
# Keys are LLMProvider values.  Values are frozensets of approved model names.
#
# Rules:
#   • Only add models you have explicitly tested with EAAWP tooling.
#   • Removing a model here immediately rejects any stored role config
#     that references it — notify operators before removing.
#   • This list intentionally mirrors the validator in RoleConfigUpdate
#     (schemas/role_config.py).  If you add a model here, add it there too.

ALLOWED_MODELS: dict[str, frozenset[str]] = {
    LLMProvider.OPENAI: frozenset({
        "gpt-4o-mini",     # default — fast, cost-effective
        "gpt-4o",          # higher capability
        "gpt-4-turbo",     # legacy high-capability
        "gpt-3.5-turbo",   # legacy fast
    }),
    LLMProvider.GOOGLE: frozenset({
        "gemini-3.5-flash-lite",               # current default — low-latency, cost-effective
        "gemini-3.8-flash",                    # retained for accounts where still available
        "gemini-2.5-flash",                    # retained for accounts where still available
        "gemini-2.5-flash-preview-04-17",      # preview alias retained for existing configs
        "gemini-1.5-flash",                    # fast, widely supported
        "gemini-1.5-flash-8b",                 # smaller / lower-cost variant
        "gemini-1.5-pro",                      # highest capability Gemini 1.5
        "gemini-2.0-flash",                    # kept for existing deployments
        "gemini-2.0-flash-lite",               # kept for existing deployments
    }),
}

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_PROVIDER: LLMProvider = LLMProvider.OPENAI
DEFAULT_MODEL: str = "gpt-4o-mini"
DEFAULT_TEMPERATURE: float = 0.0   # deterministic by default; content_service overrides


def _get_default_provider() -> LLMProvider:
    "Return runtime default provider (reads env at call time, not import time)."
    import os
    from app.config import settings
    prov = (os.environ.get('LLM_DEFAULT_PROVIDER') or settings.llm_default_provider or 'openai').lower().strip()
    return LLMProvider.GOOGLE if prov == 'google' else LLMProvider.OPENAI


def _get_default_model() -> str:
    "Return runtime default model."
    import os
    from app.config import settings
    if _get_default_provider() == LLMProvider.GOOGLE:
        return (os.environ.get('GEMINI_DEFAULT_MODEL') or settings.gemini_default_model or 'gemini-3.5-flash-lite')
    return (os.environ.get('LLM_DEFAULT_MODEL') or settings.llm_default_model or 'gpt-4o-mini')


# ── LLMConfig ─────────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    """
    Validated, immutable LLM configuration.

    Usage:
        cfg = LLMConfig(api_key="sk-...", model="gpt-4o-mini")
        # or with explicit provider:
        cfg = LLMConfig(api_key="sk-...", provider="openai", model="gpt-4o")

    The api_key is stored in a private Pydantic field so it is excluded
    from .model_dump(), __repr__(), and any serialisation path.  Access
    it only via cfg.api_key inside the provider layer — never log it.
    """

    model_config = {"frozen": True}   # immutable after construction

    provider: LLMProvider = Field(default=DEFAULT_PROVIDER)
    model: str = Field(default=DEFAULT_MODEL)
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=128_000)
    timeout: int | None = Field(default=None, ge=1, le=300, description="Request timeout in seconds")

    # Private — never serialised.  Uses Pydantic's private attribute mechanism.
    _api_key: str = ""

    def __init__(self, *, api_key: str = "", **data: Any) -> None:
        super().__init__(**data)
        # Bypass frozen to initialise the private attribute
        object.__setattr__(self, "_api_key", api_key)

    @property
    def api_key(self) -> str:
        """Access the API key.  Never log or return this in an API response."""
        return self._api_key

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("provider", mode="before")
    @classmethod
    def normalise_provider(cls, v: Any) -> LLMProvider:
        if isinstance(v, LLMProvider):
            return v
        if isinstance(v, str):
            try:
                return LLMProvider(v.lower())
            except ValueError:
                valid = [p.value for p in LLMProvider]
                raise ValueError(
                    f"Unknown provider '{v}'. Supported providers: {valid}"
                ) from None
        raise ValueError(f"provider must be a string, got {type(v).__name__}")

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        # ge/le constraints catch the range; this adds a precision guard
        if not isinstance(v, (int, float)):
            raise ValueError("temperature must be a number")
        return float(round(v, 4))

    @model_validator(mode="after")
    def validate_model_allowed(self) -> "LLMConfig":
        allowed = ALLOWED_MODELS.get(self.provider, frozenset())
        if self.model not in allowed:
            raise LLMUnsupportedModelError(self.provider.value, self.model)
        return self

    # ── Safe representations (never include api_key) ──────────────────────────

    def __repr__(self) -> str:
        return (
            f"LLMConfig(provider={self.provider.value!r}, "
            f"model={self.model!r}, "
            f"temperature={self.temperature}, "
            f"api_key='[REDACTED]')"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def safe_dict(self) -> dict:
        """
        Return a serialisation-safe dict with api_key redacted.
        Use this for health checks, admin APIs, and logging.
        """
        return {
            "provider": self.provider.value,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "api_key_present": bool(self._api_key),
        }

    def has_api_key(self) -> bool:
        """Return True if an API key is configured (does not validate the key)."""
        return bool(self._api_key and self._api_key.strip())


# ── Factory helper: build LLMConfig from application Settings ─────────────────

def llm_config_from_settings(
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> LLMConfig:
    """
    Construct a validated LLMConfig from the application settings singleton.

    Provider selection logic:
    1. If `model` is explicitly passed, its name is used to detect the provider:
       - Gemini model names (gemini-*) → LLMProvider.GOOGLE
       - Everything else → LLMProvider.OPENAI
    2. If no model is passed, LLM_DEFAULT_PROVIDER env var determines the provider.
       - "google"  → Gemini with GEMINI_DEFAULT_MODEL
       - "openai" (default) → OpenAI with LLM_DEFAULT_MODEL
    3. Falls back to OpenAI if Gemini is requested but GEMINI_API_KEY is missing.

    Never logs or exposes API key values.
    """
    from app.config import settings  # lazy import to avoid circular deps
    import os

    # Read API keys fresh from environment too (supports test monkeypatching)
    openai_key = os.environ.get("OPENAI_API_KEY", settings.openai_api_key)
    gemini_key = os.environ.get("GEMINI_API_KEY", settings.gemini_api_key)
    default_provider_str = (
        os.environ.get("LLM_DEFAULT_PROVIDER")
        or settings.llm_default_provider
        or "openai"
    ).lower().strip()
    default_model = os.environ.get("LLM_DEFAULT_MODEL") or settings.llm_default_model
    gemini_model = os.environ.get("GEMINI_DEFAULT_MODEL") or settings.gemini_default_model or "gemini-3.5-flash-lite"

    # ── Determine provider and model ──────────────────────────────────────────
    resolved_model = model  # may be None
    resolved_provider: LLMProvider

    if resolved_model is not None and resolved_model.startswith("gemini"):
        resolved_provider = LLMProvider.GOOGLE
    elif resolved_model is not None:
        resolved_provider = LLMProvider.OPENAI
    else:
        if default_provider_str == "google":
            resolved_provider = LLMProvider.GOOGLE
            resolved_model = gemini_model
        else:
            resolved_provider = LLMProvider.OPENAI
            resolved_model = default_model

    # ── Resolve API key ───────────────────────────────────────────────────────
    if resolved_provider == LLMProvider.GOOGLE:
        api_key = gemini_key
        if not api_key or not api_key.strip():
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not configured. "
                "Set it in backend/.env to use Google Gemini models."
            )
    else:
        api_key = openai_key
        if not api_key or not api_key.strip():
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured. "
                "Set it in backend/.env or as an environment variable."
            )

    # ── Build validated config ────────────────────────────────────────────────
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "provider": resolved_provider,
        "model": resolved_model,
        "temperature": temperature if temperature is not None else DEFAULT_TEMPERATURE,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if timeout is not None:
        kwargs["timeout"] = timeout

    return LLMConfig(**kwargs)
