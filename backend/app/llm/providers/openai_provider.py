"""
EAAWP LLM Gateway — OpenAI provider implementation.

Wraps langchain_openai.ChatOpenAI with the EAAWP provider interface.

The produced ChatOpenAI instance is functionally equivalent to the
instances previously scattered across engine.py, planner.py,
content_service.py, and config_interpreter.py:

    Before (per call site):
        ChatOpenAI(model="gpt-4o-mini", temperature=0)

    After (via gateway):
        gateway.get_chat_model(config)
        # internally: ChatOpenAI(model=config.model,
        #                        temperature=config.temperature,
        #                        api_key=config.api_key,
        #                        ...)

Security notes:
    • api_key is passed directly to ChatOpenAI's constructor, not set as an
      environment variable or logged anywhere in this file.
    • The config object's __repr__ never includes the key (see LLMConfig).
    • ChatOpenAI will also auto-detect OPENAI_API_KEY from the environment if
      the explicit key happens to be empty, but our LLMConfig validator already
      rejects empty keys at construction time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_openai import ChatOpenAI

from app.llm.exceptions import LLMProviderError
from app.llm.providers.base import BaseLLMProvider

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from app.llm.config import LLMConfig


class OpenAIProvider(BaseLLMProvider):
    """
    Concrete provider for OpenAI chat completions via langchain_openai.

    Produces a ChatOpenAI instance configured from the supplied LLMConfig.
    The instance supports:
        • .ainvoke(messages)        — all existing async call sites
        • .invoke(messages)         — any sync usage
        • .bind_tools(tools)        — DynamicAgentEngine's tool binding
    """

    @property
    def provider_name(self) -> str:
        return "openai"

    def get_chat_model(self, config: "LLMConfig") -> "BaseChatModel":
        """
        Build a ChatOpenAI instance from the validated config.

        Args:
            config: Validated LLMConfig for an OPENAI provider.

        Returns:
            ChatOpenAI instance ready for .ainvoke() / .bind_tools().

        Raises:
            LLMProviderError: if ChatOpenAI cannot be initialised.
        """
        try:
            kwargs: dict[str, Any] = {
                "model": config.model,
                "temperature": config.temperature,
                "api_key": config.api_key,
            }
            if config.max_tokens is not None:
                kwargs["max_tokens"] = config.max_tokens
            if config.timeout is not None:
                kwargs["timeout"] = config.timeout

            return ChatOpenAI(**kwargs)
        except Exception as exc:
            # Never include the api_key in the error message
            raise LLMProviderError(
                f"Failed to initialise OpenAI provider with model '{config.model}': {exc}"
            ) from exc
