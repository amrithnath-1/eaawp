"""
EAAWP Dynamic Integration Framework — Integration Provider Registry

The IntegrationRegistry is the single source of truth for every
registered provider type in the platform.

It maps provider_type strings → IntegrationProvider instances.

Phase 1 providers (DB connections, email, channels) are preserved in their
own existing subsystems.  The registry adds a unified lookup layer so the
Integration Manager can discover any provider by type string without
hardcoded conditionals.

Adding a new provider
─────────────────────
1. Create a subclass of IntegrationProvider (see app/integrations/providers/).
2. Call:

    from app.integrations.integration_registry import integration_registry
    integration_registry.register(MyProvider())

   This is typically done in the provider's own module at import time,
   or in this file for built-in providers.

3. The Integration Manager, API router, and future tool-registration layer
   will automatically discover the new provider — no other changes needed.

Thread safety
─────────────
Registration is expected to happen once at module import time.
The registry is read-only during request handling.
No locking is needed in Python's GIL-protected single-process server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.provider import IntegrationProvider, ProviderCapability

logger = logging.getLogger(__name__)


class IntegrationRegistry:
    """
    Application-level registry of IntegrationProvider instances.

    Providers are registered by their `provider_type` string.
    The registry is populated at import time; request handlers use it
    read-only.

    Usage:
        # Register a provider (done once at startup)
        integration_registry.register(PostgreSQLIntegrationProvider())

        # Look up a provider
        provider = integration_registry.get("postgresql")

        # List all registered types
        types = integration_registry.list_types()
    """

    def __init__(self) -> None:
        self._providers: dict[str, "IntegrationProvider"] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, provider: "IntegrationProvider") -> None:
        """
        Register a provider instance.

        If a provider for the same type is already registered, it is replaced
        and a warning is logged (to catch accidental double-registration).

        Args:
            provider: A concrete IntegrationProvider instance.
        """
        ptype = provider.provider_type
        if ptype in self._providers:
            logger.warning(
                "IntegrationRegistry: replacing existing provider for type %r", ptype
            )
        self._providers[ptype] = provider
        logger.debug("IntegrationRegistry: registered provider %r", ptype)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, provider_type: str) -> "IntegrationProvider | None":
        """Return the provider for the given type, or None if not registered."""
        return self._providers.get(provider_type)

    def get_or_raise(self, provider_type: str) -> "IntegrationProvider":
        """
        Return the provider or raise ValueError if not registered.
        Use this inside the Integration Manager where an unknown type
        should produce a clear user-facing error.
        """
        provider = self._providers.get(provider_type)
        if provider is None:
            available = sorted(self._providers.keys())
            raise ValueError(
                f"Unknown integration provider type '{provider_type}'. "
                f"Registered types: {available}"
            )
        return provider

    def has(self, provider_type: str) -> bool:
        """Return True if a provider is registered for the given type."""
        return provider_type in self._providers

    # ── Discovery ─────────────────────────────────────────────────────────────

    def list_types(self) -> list[str]:
        """Return all registered provider type strings, sorted."""
        return sorted(self._providers.keys())

    def list_providers(self) -> list["IntegrationProvider"]:
        """Return all registered provider instances, sorted by type."""
        return [self._providers[k] for k in sorted(self._providers.keys())]

    def all_capabilities(self) -> dict[str, list["ProviderCapability"]]:
        """
        Return a dict mapping provider_type → list of capabilities.
        Useful for admin overview UIs and automated testing.
        """
        return {
            ptype: provider.get_capabilities()
            for ptype, provider in self._providers.items()
        }

    def provider_catalogue(self) -> list[dict]:
        """
        Return a safe, serialisable catalogue of all registered providers.
        Used by the /api/v1/integration-manager/providers endpoint.
        Never includes credentials or sensitive configuration.
        """
        catalogue = []
        for provider in self.list_providers():
            catalogue.append({
                "provider_type": provider.provider_type,
                "display_name": provider.display_name,
                "description": provider.description,
                "icon_hint": provider.icon_hint,
                "required_credential_fields": provider.required_credential_fields(),
                "optional_credential_fields": provider.optional_credential_fields(),
                "capabilities": [
                    {
                        "key": cap.key,
                        "display_name": cap.display_name,
                        "description": cap.description,
                        "category": cap.category.value,
                        "risk_level": cap.risk_level.value,
                        "requires_schema_entity": cap.requires_schema_entity,
                    }
                    for cap in provider.get_capabilities()
                ],
            })
        return catalogue

    def __repr__(self) -> str:
        return f"<IntegrationRegistry providers={self.list_types()}>"


# ── Application singleton ─────────────────────────────────────────────────────

integration_registry = IntegrationRegistry()


# ── Register built-in Phase 2 providers ──────────────────────────────────────
# Providers are imported here so they self-register via the module-level call
# at the bottom of each provider file.
#
# Add new providers by importing them here.
# The import itself triggers registration.

def _register_builtin_providers() -> None:
    """
    Register all built-in providers shipped with the platform.
    Called once at module load time.
    """
    try:
        from app.integrations.providers.postgresql_provider import (  # noqa: F401
            PostgreSQLIntegrationProvider,
        )
        integration_registry.register(PostgreSQLIntegrationProvider())
    except Exception as exc:
        logger.warning("Could not register postgresql provider: %s", exc)

    try:
        from app.integrations.providers.mysql_provider import (  # noqa: F401
            MySQLIntegrationProvider,
        )
        integration_registry.register(MySQLIntegrationProvider())
    except Exception as exc:
        logger.warning("Could not register mysql provider: %s", exc)

    # Phase 4 — Google Search Console (real OAuth2 integration)
    try:
        from app.integrations.providers.google_search_console_provider import (
            GoogleSearchConsoleProvider,
        )
        integration_registry.register(GoogleSearchConsoleProvider())
    except Exception as exc:
        logger.warning("Could not register google_search_console provider: %s", exc)

    # Phase D — Google Analytics
    try:
        from app.integrations.providers.google_analytics_provider import (
            GoogleAnalyticsProvider,
        )
        integration_registry.register(GoogleAnalyticsProvider())
    except Exception as exc:
        logger.warning("Could not register google_analytics provider: %s", exc)

    # Phase E — Meta / Facebook
    try:
        from app.integrations.providers.facebook_provider import FacebookProvider
        integration_registry.register(FacebookProvider())
    except Exception as exc:
        logger.warning("Could not register facebook provider: %s", exc)

    # Phase F — GitHub
    try:
        from app.integrations.providers.github_provider import GitHubProvider
        integration_registry.register(GitHubProvider())
    except Exception as exc:
        logger.warning("Could not register github provider: %s", exc)

    # Phase G — MCP
    try:
        from app.integrations.providers.mcp_provider import MCPIntegrationProvider
        integration_registry.register(MCPIntegrationProvider())
    except Exception as exc:
        logger.warning("Could not register mcp provider: %s", exc)


_register_builtin_providers()
