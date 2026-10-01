"""
EAAWP Data Connector Abstraction

Defines the BaseConnector interface that all external data source adapters
must implement. The Universal AI Core and DynamicAgentEngine are completely
unaware of any specific connector implementation.

Security contract
-----------------
- Connectors receive a plain-text password ONLY at connection time.
- Passwords are NEVER stored in connector instances beyond the test call.
- All schema discovery returns metadata only — no data rows.
- SQL execution is NOT exposed through this interface in this phase.
- The connector validates that it can reach the server before returning
  a "connected" status.

Supported connectors (this file):
  PostgreSQLConnector  — connects via asyncpg (async) or psycopg2 (sync fallback)
  MySQLConnector       — connects via aiomysql (async) or mysql-connector-python

Both connectors are instantiated fresh for each operation.
No long-lived connection pools are held — this is metadata-only usage.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ColumnMeta:
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False


@dataclass
class EntityMeta:
    schema_name: str
    entity_name: str
    entity_type: str           # "table" | "view"
    columns: list[ColumnMeta] = field(default_factory=list)
    row_count_estimate: int | None = None


@dataclass
class TestResult:
    success: bool
    error_message: str | None = None
    server_version: str | None = None


# ── Base interface ────────────────────────────────────────────────────────────

class BaseConnector(abc.ABC):
    """
    Abstract base class for all external data source connectors.
    Implementations must not retain credentials after the operation completes.
    """

    @abc.abstractmethod
    async def test_connection(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> TestResult:
        """
        Attempt to connect and return the server version.
        Must close the connection before returning.
        Never raises — always returns a TestResult.
        """

    @abc.abstractmethod
    async def discover_schema(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> list[EntityMeta]:
        """
        Connect, enumerate tables/views and their columns, then disconnect.
        Returns metadata only — no row data.
        Raises RuntimeError on failure.
        """


# ── PostgreSQL connector ──────────────────────────────────────────────────────

class PostgreSQLConnector(BaseConnector):
    """
    Connects to a PostgreSQL database to test connectivity and discover schema.
    Uses asyncpg if available; falls back to a threaded psycopg2 approach.
    Credentials are used once and discarded.
    """

    async def test_connection(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> TestResult:
        try:
            import asyncpg  # type: ignore[import]
            conn = await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=username,
                password=password,
                ssl="require" if ssl else "disable",
                timeout=10,
            )
            try:
                version = await conn.fetchval("SELECT version()")
            finally:
                await conn.close()
            return TestResult(success=True, server_version=str(version)[:120] if version else None)
        except ImportError:
            return await self._test_via_sync(host, port, database, username, password, ssl)
        except Exception as exc:
            logger.warning("PostgreSQL test_connection failed: %s", exc)
            return TestResult(success=False, error_message=_sanitise_error(str(exc)))

    async def _test_via_sync(
        self, host: str, port: int, database: str, username: str, password: str, ssl: bool
    ) -> TestResult:
        """Fallback: run psycopg2 in a thread executor."""
        def _sync() -> TestResult:
            try:
                import psycopg2  # type: ignore[import]
                conn = psycopg2.connect(
                    host=host, port=port, dbname=database,
                    user=username, password=password,
                    sslmode="require" if ssl else "disable",
                    connect_timeout=10,
                )
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT version()")
                    row = cur.fetchone()
                    version = row[0] if row else None
                finally:
                    conn.close()
                return TestResult(success=True, server_version=str(version)[:120] if version else None)
            except Exception as exc:
                return TestResult(success=False, error_message=_sanitise_error(str(exc)))

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)

    async def discover_schema(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> list[EntityMeta]:
        try:
            import asyncpg  # type: ignore[import]
            conn = await asyncpg.connect(
                host=host, port=port, database=database,
                user=username, password=password,
                ssl="require" if ssl else "disable",
                timeout=10,
            )
            try:
                return await self._asyncpg_discover(conn)
            finally:
                await conn.close()
        except ImportError:
            return await self._discover_via_sync(host, port, database, username, password, ssl)

    async def _asyncpg_discover(self, conn: Any) -> list[EntityMeta]:
        # Fetch tables and views (information_schema is standard SQL)
        rows = await conn.fetch("""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """)
        entities: list[EntityMeta] = []
        for row in rows:
            schema = row["table_schema"]
            table = row["table_name"]
            etype = "view" if row["table_type"] == "VIEW" else "table"
            col_rows = await conn.fetch("""
                SELECT column_name, data_type,
                       CASE WHEN is_nullable = 'YES' THEN true ELSE false END AS is_nullable
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
            """, schema, table)
            pk_rows = await conn.fetch("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = $1 AND tc.table_name = $2
            """, schema, table)
            pk_cols = {r["column_name"] for r in pk_rows}
            columns = [
                ColumnMeta(
                    name=c["column_name"],
                    data_type=c["data_type"],
                    is_nullable=bool(c["is_nullable"]),
                    is_primary_key=c["column_name"] in pk_cols,
                )
                for c in col_rows
            ]
            # Row count estimate from pg_stat
            try:
                est_row = await conn.fetchrow(
                    "SELECT reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = $1 AND c.relname = $2", schema, table
                )
                row_est = int(est_row["reltuples"]) if est_row and est_row["reltuples"] else None
            except Exception:
                row_est = None
            entities.append(EntityMeta(
                schema_name=schema,
                entity_name=table,
                entity_type=etype,
                columns=columns,
                row_count_estimate=row_est,
            ))
        return entities

    async def _discover_via_sync(
        self, host: str, port: int, database: str, username: str, password: str, ssl: bool
    ) -> list[EntityMeta]:
        def _sync() -> list[EntityMeta]:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras  # type: ignore[import]
            conn = psycopg2.connect(
                host=host, port=port, dbname=database,
                user=username, password=password,
                sslmode="require" if ssl else "disable",
                connect_timeout=10,
            )
            conn.autocommit = True
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                cur.execute("""
                    SELECT table_schema, table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, table_name
                """)
                table_rows = cur.fetchall()
                entities: list[EntityMeta] = []
                for trow in table_rows:
                    schema, table, ttype = trow["table_schema"], trow["table_name"], trow["table_type"]
                    cur.execute("""
                        SELECT column_name, data_type,
                               CASE WHEN is_nullable = 'YES' THEN true ELSE false END AS is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                    """, (schema, table))
                    col_rows = cur.fetchall()
                    cur.execute("""
                        SELECT kcu.column_name FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = %s AND tc.table_name = %s
                    """, (schema, table))
                    pk_cols = {r["column_name"] for r in cur.fetchall()}
                    columns = [
                        ColumnMeta(
                            name=c["column_name"],
                            data_type=c["data_type"],
                            is_nullable=bool(c["is_nullable"]),
                            is_primary_key=c["column_name"] in pk_cols,
                        )
                        for c in col_rows
                    ]
                    entities.append(EntityMeta(
                        schema_name=schema, entity_name=table,
                        entity_type="view" if ttype == "VIEW" else "table",
                        columns=columns,
                    ))
                return entities
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)


# ── MySQL connector ───────────────────────────────────────────────────────────

class MySQLConnector(BaseConnector):
    """
    Connects to a MySQL/MariaDB database.
    Uses aiomysql if available; falls back to mysql-connector-python in a thread.
    """

    async def test_connection(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> TestResult:
        try:
            import aiomysql  # type: ignore[import]
            conn = await aiomysql.connect(
                host=host, port=port, db=database,
                user=username, password=password,
                ssl={"ssl_ca": None} if ssl else None,
                connect_timeout=10,
            )
            try:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT VERSION()")
                    row = await cur.fetchone()
                    version = row[0] if row else None
            finally:
                conn.close()
            return TestResult(success=True, server_version=str(version)[:120] if version else None)
        except ImportError:
            return await self._test_via_sync(host, port, database, username, password, ssl)
        except Exception as exc:
            logger.warning("MySQL test_connection failed: %s", exc)
            return TestResult(success=False, error_message=_sanitise_error(str(exc)))

    async def _test_via_sync(
        self, host: str, port: int, database: str, username: str, password: str, ssl: bool
    ) -> TestResult:
        def _sync() -> TestResult:
            try:
                import mysql.connector  # type: ignore[import]
                conn = mysql.connector.connect(
                    host=host, port=port, database=database,
                    user=username, password=password,
                    ssl_disabled=not ssl,
                    connection_timeout=10,
                )
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT VERSION()")
                    row = cur.fetchone()
                    version = row[0] if row else None
                finally:
                    conn.close()
                return TestResult(success=True, server_version=str(version)[:120] if version else None)
            except Exception as exc:
                return TestResult(success=False, error_message=_sanitise_error(str(exc)))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)

    async def discover_schema(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> list[EntityMeta]:
        def _sync_discover() -> list[EntityMeta]:
            # MySQL information_schema queries work the same as PostgreSQL
            try:
                import mysql.connector  # type: ignore[import]
                conn = mysql.connector.connect(
                    host=host, port=port, database=database,
                    user=username, password=password,
                    ssl_disabled=not ssl,
                    connection_timeout=10,
                )
                try:
                    cur = conn.cursor(dictionary=True)
                    cur.execute("""
                        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                        FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = %s
                        ORDER BY TABLE_NAME
                    """, (database,))
                    table_rows = cur.fetchall()
                    entities: list[EntityMeta] = []
                    for trow in table_rows:
                        schema = str(trow["TABLE_SCHEMA"])
                        table = str(trow["TABLE_NAME"])
                        ttype = str(trow["TABLE_TYPE"])
                        cur.execute("""
                            SELECT COLUMN_NAME, DATA_TYPE,
                                   CASE WHEN IS_NULLABLE = 'YES' THEN 1 ELSE 0 END AS is_nullable,
                                   CASE WHEN COLUMN_KEY = 'PRI' THEN 1 ELSE 0 END AS is_pk
                            FROM information_schema.COLUMNS
                            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                            ORDER BY ORDINAL_POSITION
                        """, (schema, table))
                        columns = [
                            ColumnMeta(
                                name=str(c["COLUMN_NAME"]),
                                data_type=str(c["DATA_TYPE"]),
                                is_nullable=bool(c["is_nullable"]),
                                is_primary_key=bool(c["is_pk"]),
                            )
                            for c in cur.fetchall()
                        ]
                        entities.append(EntityMeta(
                            schema_name=schema, entity_name=table,
                            entity_type="view" if "VIEW" in ttype.upper() else "table",
                            columns=columns,
                        ))
                    return entities
                finally:
                    conn.close()
            except Exception as exc:
                raise RuntimeError(f"MySQL schema discovery failed: {_sanitise_error(str(exc))}") from exc

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_discover)


# ── Registry ──────────────────────────────────────────────────────────────────

_CONNECTOR_REGISTRY: dict[str, BaseConnector] = {
    "postgresql": PostgreSQLConnector(),
    "mysql": MySQLConnector(),
}


def get_connector(db_type: str) -> BaseConnector:
    """
    Return the connector for the given database type.
    Raises ValueError for unsupported types.
    """
    connector = _CONNECTOR_REGISTRY.get(db_type.lower())
    if connector is None:
        raise ValueError(
            f"Unsupported database type '{db_type}'. "
            f"Supported: {sorted(_CONNECTOR_REGISTRY.keys())}"
        )
    return connector


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitise_error(msg: str) -> str:
    """
    Remove potentially sensitive content (passwords, DSNs, paths) from
    error messages before storing them or returning them to the frontend.
    """
    import re
    # Mask anything that looks like a password= or password: in error text
    msg = re.sub(r"(?i)(password\s*[=:]\s*)\S+", r"\1[REDACTED]", msg)
    # Mask DSN-style connection strings
    msg = re.sub(r"(?i)(://[^:@]+:[^@]+@)", "://[REDACTED]@", msg)
    return msg[:500]
