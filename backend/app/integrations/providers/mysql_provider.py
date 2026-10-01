"""
EAAWP Integration Framework — MySQL Provider

Wraps the existing MySQLConnector from app.integrations.connector.
Identical in structure to PostgreSQLIntegrationProvider.

Capabilities exposed
────────────────────
  discover_schema   READ    — enumerate tables/views and column metadata
  query_entity      READ    — parameterised SELECT (via data_access service)
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


class MySQLIntegrationProvider(IntegrationProvider):
    """
    Integration Framework provider for MySQL / MariaDB databases.
    Delegates to the existing MySQLConnector.
    """

    @property
    def provider_type(self) -> str:
        return "mysql"

    @property
    def display_name(self) -> str:
        return "MySQL / MariaDB Database"

    @property
    def description(self) -> str:
        return (
            "Connect to a MySQL or MariaDB database. "
            "Supports schema discovery and controlled, read-only queries."
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
                    "Enumerate all accessible tables and views with column "
                    "definitions. Returns metadata only — no data rows."
                ),
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
            ),
            ProviderCapability(
                key="query_entity",
                display_name="Query Table / View",
                description=(
                    "Execute a parameterised, read-only SELECT against an "
                    "allowed table or view."
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
        try:
            from app.integrations.connector import MySQLConnector
            connector = MySQLConnector()
            result = await connector.test_connection(
                host=str(credentials["host"]),
                port=int(credentials.get("port", 3306)),
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
        if capability_key == "discover_schema":
            return await self._execute_discover_schema(credentials)
        elif capability_key == "query_entity":
            return CapabilityResult(
                error=(
                    "query_entity must be executed through the Integration Manager "
                    "which provides the tenant DB session context."
                )
            )
        else:
            return CapabilityResult(
                error=f"Unknown capability '{capability_key}' for provider 'mysql'."
            )

    async def _execute_discover_schema(
        self,
        credentials: dict[str, Any],
    ) -> CapabilityResult:
        try:
            from app.integrations.connector import MySQLConnector
            connector = MySQLConnector()
            entities = await connector.discover_schema(
                host=str(credentials["host"]),
                port=int(credentials.get("port", 3306)),
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
                source_label="MySQL schema discovery",
            )
        except KeyError as exc:
            return CapabilityResult(error=f"Missing credential field: {exc}")
        except Exception as exc:
            return CapabilityResult(error=self._sanitise_error(str(exc)))

    async def discover_entities(
        self,
        credentials: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result = await self._execute_discover_schema(credentials)
        if result.error:
            return []
        return result.data if isinstance(result.data, list) else []
