"""
EAAWP Company Integration Layer — Base Interface

This module defines the abstract interface that every company data source
adapter must implement.

Architecture principle
----------------------
The Universal AI Core (DynamicAgentEngine) NEVER accesses company databases
directly. It calls tools from MASTER_TOOL_REGISTRY. Those tools call
CompanyDataSource.query() — a controlled, schema-agnostic abstraction.

This means:
- Different companies can have completely different database engines,
  schemas, table names, column names, and data types.
- The AI Core never holds a database connection to an external system.
- The Integration Layer performs schema discovery and translates between
  the company's data model and the AI's tool contracts.
- SQL injection and unrestricted query execution are structurally prevented
  because the AI never writes raw SQL.

To add a new company data source:
1. Subclass CompanyDataSource.
2. Implement query() and discover_schema().
3. Register the adapter in the CompanyIntegrationRegistry.
4. The AI employee's allowed tools automatically route through it.

This file does NOT implement any real adapters — that is a future task.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class QueryResult:
    """Typed result from a company data source query."""

    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    source_label: str  # human-readable label for audit / citation


@dataclass
class SchemaInfo:
    """Metadata about a discovered data source schema."""

    source_type: str          # e.g. "postgresql", "mysql", "rest_api", "csv"
    source_label: str
    tables_or_endpoints: list[str]
    sample_columns: dict[str, list[str]]  # table/endpoint -> column names
    notes: str = ""


class CompanyDataSource(ABC):
    """
    Abstract base for all company data source adapters.

    Every adapter must be tenant-isolated: it only exposes data for the
    company it was instantiated with.
    """

    @property
    @abstractmethod
    def tenant_id(self) -> str:
        """The company this adapter serves."""

    @abstractmethod
    async def query(
        self,
        intent: str,
        parameters: dict[str, Any],
    ) -> QueryResult:
        """
        Execute a structured query against the company's data source.

        Args:
            intent:     A semantic intent string (e.g. "get_campaign_performance").
                        The adapter translates this to the appropriate query for
                        its underlying data source.
            parameters: Typed parameters for the query. Never raw SQL.

        Returns:
            QueryResult with typed rows and metadata.

        Raises:
            NotImplementedError: If the intent is not supported by this adapter.
            PermissionError: If the query would exceed the adapter's allowed scope.
        """

    @abstractmethod
    async def discover_schema(self) -> SchemaInfo:
        """
        Inspect the data source and return metadata about its structure.
        Used during adapter setup and for AI context building.
        """


class CompanyIntegrationRegistry:
    """
    Resolves the correct CompanyDataSource adapter for a given tenant.

    Future adapters to register here:
    - PostgreSQLAdapter(tenant_id, connection_string)
    - MySQLAdapter(tenant_id, connection_string)
    - RestAPIAdapter(tenant_id, base_url, auth_config)
    - CSVAdapter(tenant_id, file_path)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, CompanyDataSource] = {}

    def register(self, adapter: CompanyDataSource) -> None:
        self._adapters[adapter.tenant_id] = adapter

    def get(self, tenant_id: str) -> CompanyDataSource | None:
        return self._adapters.get(tenant_id)

    def has(self, tenant_id: str) -> bool:
        return tenant_id in self._adapters


# Global singleton — populated at application startup when adapters are configured
integration_registry = CompanyIntegrationRegistry()
