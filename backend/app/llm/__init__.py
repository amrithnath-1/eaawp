"""
EAAWP LLM Gateway — public surface.

Import from here:

    from app.llm import get_llm_gateway
    from app.llm import LLMConfig, LLMProvider

Only these names are part of the stable public API for Phase 1.
"""

from app.llm.config import LLMConfig, LLMProvider
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMProviderError,
    LLMUnsupportedModelError,
)

__all__ = [
    # Config / enums
    "LLMConfig",
    "LLMProvider",
    # Gateway
    "LLMGateway",
    "get_llm_gateway",
    # Exceptions
    "LLMConfigurationError",
    "LLMProviderError",
    "LLMUnsupportedModelError",
]
