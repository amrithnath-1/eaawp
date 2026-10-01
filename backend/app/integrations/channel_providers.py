"""
EAAWP Marketing Channel Provider Abstraction

Defines the interface all channel providers must implement.
MockChannelProvider provides safe test behavior.
Real providers can be added without modifying the agent core.

Security: Credentials are always stored encrypted in MarketingChannelIntegration.
          The decrypt + use pattern matches the existing SMTP provider pattern.
          No credentials are ever returned to the frontend or LLM.
          All publishing is HIGH risk and requires human approval.
"""
from __future__ import annotations
import abc
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChannelTestResult:
    success: bool
    account_info: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class ContentPrepareResult:
    success: bool
    prepared_content: dict[str, Any] = field(default_factory=dict)
    validation_warnings: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class PublishResult:
    success: bool
    provider_post_id: str | None = None
    provider_url: str | None = None
    provider_message: str | None = None
    error_message: str | None = None


class BaseChannelProvider(abc.ABC):
    """Abstract interface for all marketing channel providers."""

    @property
    @abc.abstractmethod
    def channel_type(self) -> str:
        """e.g. 'social_linkedin', 'email_marketing', 'cms'"""

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """e.g. 'mock', 'linkedin_api', 'mailchimp'"""

    @abc.abstractmethod
    async def validate_connection(self, credentials: dict[str, Any]) -> ChannelTestResult:
        """Test connectivity and return account info. Never stores credentials."""

    @abc.abstractmethod
    async def get_capabilities(self) -> list[str]:
        """Return list of supported actions."""

    @abc.abstractmethod
    async def prepare_content(
        self,
        content: dict[str, Any],
        channel_config: dict[str, Any],
    ) -> ContentPrepareResult:
        """
        Validate and prepare content for publication.
        LOW risk — no external side effect.
        Returns prepared content for human review.
        """

    @abc.abstractmethod
    async def publish_content(
        self,
        prepared_content: dict[str, Any],
        credentials: dict[str, Any],
    ) -> PublishResult:
        """
        Publish content to the external channel.
        HIGH risk — only called after human approval.
        Never called directly by the LLM.
        """


class MockChannelProvider(BaseChannelProvider):
    """
    Safe mock provider for testing and demo purposes.
    Simulates a marketing channel without any real external calls.
    Records all actions for audit purposes.
    """

    def __init__(self, channel_type: str = "mock") -> None:
        self._channel_type = channel_type

    @property
    def channel_type(self) -> str:
        return self._channel_type

    @property
    def provider_name(self) -> str:
        return "mock"

    async def validate_connection(self, credentials: dict[str, Any]) -> ChannelTestResult:
        # Mock: always succeeds for demo
        return ChannelTestResult(
            success=True,
            account_info={"account": "mock-account", "name": "Mock Marketing Channel"},
            capabilities=["post_text", "post_image", "schedule_post"],
        )

    async def get_capabilities(self) -> list[str]:
        return ["post_text", "post_image", "schedule_post", "get_analytics"]

    async def prepare_content(
        self,
        content: dict[str, Any],
        channel_config: dict[str, Any],
    ) -> ContentPrepareResult:
        body = content.get("body", "")
        warnings = []
        if len(body) > 280 and self._channel_type == "social_twitter":
            warnings.append(f"Content exceeds 280 characters ({len(body)}). Will be truncated.")
        return ContentPrepareResult(
            success=True,
            prepared_content={
                "channel": self._channel_type,
                "body": body[:280] if self._channel_type == "social_twitter" else body,
                "title": content.get("title", ""),
                "status": "prepared_mock",
            },
            validation_warnings=warnings,
        )

    async def publish_content(
        self,
        prepared_content: dict[str, Any],
        credentials: dict[str, Any],
    ) -> PublishResult:
        # Mock: records but does NOT actually publish externally
        mock_id = f"mock-post-{hash(str(prepared_content)) % 999999:06d}"
        logger.info("MOCK PUBLISH: %s on %s", mock_id, self._channel_type)
        return PublishResult(
            success=True,
            provider_post_id=mock_id,
            provider_url=f"https://mock.provider/{mock_id}",
            provider_message="[MOCK] Content published to simulated channel.",
        )


# ── Provider registry ─────────────────────────────────────────────────────────

_PROVIDER_REGISTRY: dict[str, type[BaseChannelProvider]] = {
    "mock": MockChannelProvider,
}


def register_provider(provider_name: str, cls: type[BaseChannelProvider]) -> None:
    """Register a new channel provider implementation."""
    _PROVIDER_REGISTRY[provider_name] = cls


def get_provider(provider_name: str, channel_type: str = "custom") -> BaseChannelProvider:
    """Factory — returns a provider instance for the given provider name."""
    cls = _PROVIDER_REGISTRY.get(provider_name, MockChannelProvider)
    return cls(channel_type)
