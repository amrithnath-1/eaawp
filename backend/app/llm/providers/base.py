"""
EAAWP LLM Gateway — abstract provider interface.

Every concrete provider (OpenAI, Anthropic, Google, …) MUST subclass
BaseLLMProvider and implement get_chat_model().

The return type is BaseChatModel (from langchain_core) so that:
  - All existing LangChain message flows (.ainvoke, bind_tools, etc.)
    continue to work without modification.
  - The gateway layer remains LangChain-compatible without being tied to
    any specific provider SDK.

Future providers implement this interface, register in the factory, and
the rest of EAAWP requires zero changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from app.llm.config import LLMConfig


class BaseLLMProvider(ABC):
    """
    Abstract base for all LLM provider implementations.

    Subclasses must implement:
        get_chat_model(config) → BaseChatModel

    The returned model must support:
        • .ainvoke(messages)          — async invocation
        • .invoke(messages)           — sync invocation
        • .bind_tools(tools)          — tool binding for function-calling
        • standard LangChain message types (SystemMessage, HumanMessage, …)
    """

    @abstractmethod
    def get_chat_model(self, config: "LLMConfig") -> "BaseChatModel":
        """
        Construct and return a configured chat model instance.

        The returned instance must be ready to use — do not return a
        partially-initialised object that requires further setup.

        Args:
            config: Validated LLMConfig.  The api_key is accessible via
                    config.api_key; do not log or expose it.

        Returns:
            A LangChain BaseChatModel-compatible instance.

        Raises:
            LLMProviderError: if provider-specific initialisation fails.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for diagnostics (never includes secrets)."""
