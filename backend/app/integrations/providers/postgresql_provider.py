"""
EAAWP Integration Framework — PostgreSQL Provider

Wraps the existing PostgreSQLConnector from app.integrations.connector
so that PostgreSQL appears as a first-class IntegrationProvider.

This preserves 100% of the existing connector logic — no duplication.
The existing /api/v1/integrations/ router and DataConnection ORM continue
to work unchanged.  This provider adds the new generic Integration Framework
layer on top.

Capabilities exposed
────────────────────
  discover_schema   READ    — enumerate tables/views and column metadata
  query_entity      READ    — parameterised SELECT (delegates to data_access service)
"""

from __future__ import annotations

from typing import Any

from app.integrations.provider import (
    CapabilityCategory,
    CapabilityResult,
    ConnectionTestResult,
    IntegrationProvider,
    ProviderCapability,
    RiskLevel,
)


class PostgreSQLIntegrationProvider(IntegrationProvider):
    """
    Integration Framework provider for PostgreSQL databases.

    Delegates to the existing PostgreSQLConnector for actual connectivity.
    Credentials expected:
        host, port (int), database, username, password, ssl (bool, default True)
    """

    @property
    def provider_type(self) -> str:
        return "postgresql"

    @property
    def display_name(self) -> str:
        return "PostgreSQL Database"

    @property
    def description(self) -> str:
        return (
            "Connect to a PostgreSQL database. "
            "Supports schema discovery and controlled, read-only queries "
            "through semantic mappings."
        )

    @property
    def icon_hint(self) -> str:
        return "database"

    def required_credential_fields(self) -> list[str]:
        return ["host", "port", "database", "username", "password"]

    def optional_credential_fields(self) -> list[str]:
        return ["ssl"]

    def get_capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                key="discover_schema",
                display_name="Discover Schema",
                description=(
                    "Connect to the database and enumerate all accessible "
                    "tables and views with their column definitions. "
                    "Returns metadata only — no data rows."
                ),
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema=None,
            ),
            ProviderCapability(
                key="query_entity",
                display_name="Query Table / View",
                description=(
                    "Execute a parameterised, read-only SELECT against an "
                    "allowed table or view. Filters, sort, and limit are "
                    "supported. Raw SQL is never accepted."
                ),
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                requires_schema_entity=True,
                input_schema={
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "array"},
                    "sort": {"type": "array"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            ),
        ]

    async def test_connection(
        self,
        credentials: dict[str, Any],
    ) -> ConnectionTestResult:
        """
        Delegate to the existing PostgreSQLConnector.test_connection().
        Credentials are used once and discarded.
        """
        try:
            from app.integrations.connector import PostgreSQLConnector
            from app.integrations.provider import validate_outbound_host
            host = str(credentials["host"])
            # Block SSRF before opening any network connection.
            try:
                validate_outbound_host(host)
            except ValueError as ssrf_exc:
                return ConnectionTestResult(
                    success=False,
                    error_message=str(ssrf_exc),
                )
            connector = PostgreSQLConnector()
            result = await connector.test_connection(
                host=str(credentials["host"]),
                port=int(credentials.get("port", 5432)),
                database=str(credentials["database"]),
                username=str(credentials["username"]),
                password=str(credentials["password"]),
                ssl=bool(credentials.get("ssl", True)),
            )
            return ConnectionTestResult(
                success=result.success,
                account_info={"server_version": result.server_version or "unknown"},
                error_message=result.error_message,
            )
        except KeyError as exc:
            return ConnectionTestResult(
                success=False,
                error_message=f"Missing required credential field: {exc}",
            )
        except Exception as exc:
            return ConnectionTestResult(
                success=False,
                error_message=self._sanitise_error(str(exc)),
            )

    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        """
        Execute a PostgreSQL capability.

        discover_schema — delegates to PostgreSQLConnector.discover_schema()
        query_entity    — not handled here; routed through data_access service
                          by the Integration Manager (which has DB session access)
        """
        if capability_key == "discover_schema":
            return await self._execute_discover_schema(credentials)
        elif capability_key == "query_entity":
            # query_entity requires a DB session (for SemanticMapping + audit).
            # The Integration Manager handles this via execute_company_data_query.
            # If called directly (e.g. in tests), return a guidance message.
            return CapabilityResult(
                error=(
                    "query_entity must be executed through the Integration Manager "
                    "which provides the tenant DB session context."
                )
            )
        else:
            return CapabilityResult(
                error=f"Unknown capability '{capability_key}' for provider 'postgresql'."
            )

    async def _execute_discover_schema(
        self,
        credentials: dict[str, Any],
    ) -> CapabilityResult:
        try:
            from app.integrations.connector import PostgreSQLConnector
            from app.integrations.provider import validate_outbound_host
            host = str(credentials["host"])
            try:
                validate_outbound_host(host)
            except ValueError as ssrf_exc:
                return CapabilityResult(error=str(ssrf_exc))
            connector = PostgreSQLConnector()
            entities = await connector.discover_schema(
                host=host,
                port=int(credentials.get("port", 5432)),
                database=str(credentials["database"]),
                username=str(credentials["username"]),
                password=str(credentials["password"]),
                ssl=bool(credentials.get("ssl", True)),
            )
            rows = [
                {
                    "schema_name": e.schema_name,
                    "entity_name": e.entity_name,
                    "entity_type": e.entity_type,
                    "column_count": len(e.columns),
                    "row_count_estimate": e.row_count_estimate,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_nullable": c.is_nullable,
                            "is_primary_key": c.is_primary_key,
                        }
                        for c in e.columns
                    ],
                }
                for e in entities
            ]
            return CapabilityResult(
                data=rows,
                row_count=len(rows),
                source_label=f"PostgreSQL schema discovery",
            )
        except KeyError as exc:
            return CapabilityResult(error=f"Missing credential field: {exc}")
        except Exception as exc:
            return CapabilityResult(error=self._sanitise_error(str(exc)))

    async def discover_entities(
        self,
        credentials: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Used by the Integration Manager to populate SchemaEntity records."""
        result = await self._execute_discover_schema(credentials)
        if result.error:
            return []
        return result.data if isinstance(result.data, list) else []
