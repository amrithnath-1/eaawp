"""
EAAWP LLM Gateway — Google Gemini provider implementation.

Wraps langchain_google_genai.ChatGoogleGenerativeAI with the EAAWP
provider interface so every call site (engine, planner, content service,
config interpreter, NL integration service, employee builder) gets
Gemini models through exactly the same gateway abstraction as OpenAI.

Security notes:
    • api_key is passed directly to ChatGoogleGenerativeAI's constructor
      and is never logged, printed, or included in any response.
    • The LLMConfig object's __repr__ already excludes the key.
    • If GEMINI_API_KEY is not set, the gateway health check reports
      is_ready=False and callers receive a controlled 503 — not a crash.

Tool binding:
    ChatGoogleGenerativeAI supports .bind_tools() for function calling,
    which is required by DynamicAgentEngine. Gemini models that support
    function calling (gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash,
    gemini-2.5-flash, gemini-3.8-flash)
    work identically to OpenAI tool binding from the LangChain perspective.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_google_genai import ChatGoogleGenerativeAI

from app.llm.exceptions import LLMProviderError
from app.llm.providers.base import BaseLLMProvider

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from app.llm.config import LLMConfig


class GeminiProvider(BaseLLMProvider):
    """
    Concrete provider for Google Gemini via langchain_google_genai.

    Produces a ChatGoogleGenerativeAI instance configured from LLMConfig.
    Supports:
        • .ainvoke(messages)    — async agent execution
        • .invoke(messages)     — sync paths
        • .bind_tools(tools)    — tool/function calling (gemini-1.5+)
    """

    @property
    def provider_name(self) -> str:
        return "google"

    def get_chat_model(self, config: "LLMConfig") -> "BaseChatModel":
        """
        Build a ChatGoogleGenerativeAI instance from the validated config.

        Args:
            config: Validated LLMConfig for a GOOGLE provider.

        Returns:
            ChatGoogleGenerativeAI instance ready for .ainvoke() / .bind_tools().

        Raises:
            LLMProviderError: if the model cannot be initialised.
        """
        try:
            kwargs: dict[str, Any] = {
                "model": config.model,
                "temperature": config.temperature,
                "google_api_key": config.api_key,
                # convert_system_message_to_human: Gemini models accept system
                # messages natively in the 1.5+ series; keeping False so we
                # don't silently alter system prompts.
                "convert_system_message_to_human": False,
            }
            if config.max_tokens is not None:
                kwargs["max_output_tokens"] = config.max_tokens
            if config.timeout is not None:
                kwargs["timeout"] = config.timeout

            return ChatGoogleGenerativeAI(**kwargs)

        except Exception as exc:
            # Never include the api_key in the error message
            raise LLMProviderError(
                f"Failed to initialise Gemini model '{config.model}': {exc}"
            ) from exc
