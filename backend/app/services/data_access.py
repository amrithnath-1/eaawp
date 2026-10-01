"""
EAAWP Controlled Data Access Service

This is the ONLY place that executes queries against company external databases.

Security invariants (enforced here)
-------------------------------------
1. Every request verifies: tenant → connection → entity → entity.is_allowed.
   Any failure returns an authorization error — never data.
2. No raw SQL is accepted from the agent. Only structured params.
3. All identifier names (entity, columns, filter fields, sort fields) are
   validated against the discovered schema before the query is built.
4. Queries are parameterized — values are NEVER interpolated into SQL strings.
5. Only SELECT is executed. INSERT/UPDATE/DELETE/DDL are structurally absent.
6. Result size is capped at MAX_QUERY_LIMIT rows.
7. Credentials are decrypted in memory for the query duration only — never logged.
8. Every call produces a DataAccessAudit record regardless of outcome.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataAccessAudit, DataConnection, SchemaEntity, SemanticMapping
from app.integrations.crypto import decrypt_password
from app.schemas.data_access import (
    MAX_QUERY_LIMIT,
    CompanyDataQueryRequest,
    CompanyDataQueryResponse,
    QueryFilter,
    QuerySort,
    validate_identifier,
)

logger = logging.getLogger(__name__)


# ── Main entry point ──────────────────────────────────────────────────────────

async def execute_company_data_query(
    request: CompanyDataQueryRequest,
    tenant_id: str,
    role_key: str,
    db: AsyncSession,
) -> CompanyDataQueryResponse:
    """
    Execute a controlled read-only query against an authorized company entity.

    Steps:
      1. Resolve entity (via semantic concept or direct IDs).
      2. Verify entity is_allowed.
      3. Validate requested fields against discovered schema.
      4. Build safe parameterized SELECT.
      5. Execute on external DB.
      6. Write audit record.
      7. Return structured response.

    Raises:
        PermissionError: Entity not allowed or tenant mismatch.
        ValueError: Invalid field/filter names.
        RuntimeError: External DB connection failure.
    """
    audit_id = str(uuid.uuid4())
    connection_id: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    semantic_concept: str | None = request.semantic_concept

    try:
        # ── Step 1: Resolve entity ───────────────────────────────────────────
        conn_row, entity_row, resolved_fields = await _resolve_entity(
            request, tenant_id, db
        )
        connection_id = conn_row.id
        entity_id = entity_row.id
        entity_name = entity_row.entity_name

        # ── Step 2: Validate entity is allowed ───────────────────────────────
        if not entity_row.is_allowed:
            raise PermissionError(
                f"Entity '{entity_row.entity_name}' is not authorized for AI access. "
                "An administrator must explicitly allow this entity in the Data Connections panel."
            )

        # ── Step 3: Validate requested fields against schema ─────────────────
        schema_cols = {
            c["name"] for c in json.loads(entity_row.columns_json or "[]")
        }
        if not schema_cols:
            raise ValueError(
                f"Entity '{entity_name}' has no discovered columns. Run schema discovery first."
            )

        if resolved_fields:
            bad_fields = [f for f in resolved_fields if f not in schema_cols]
            if bad_fields:
                raise ValueError(
                    f"Requested fields not found in entity '{entity_name}': {bad_fields}. "
                    f"Available columns: {sorted(schema_cols)}"
                )
            select_fields = resolved_fields
        else:
            # No fields specified — return all schema columns
            select_fields = sorted(schema_cols)

        # Validate filter and sort fields too
        for flt in request.filters:
            if flt.field not in schema_cols:
                raise ValueError(
                    f"Filter field '{flt.field}' not found in entity '{entity_name}'. "
                    f"Available: {sorted(schema_cols)}"
                )
        for srt in request.sort:
            if srt.field not in schema_cols:
                raise ValueError(
                    f"Sort field '{srt.field}' not found in entity '{entity_name}'. "
                    f"Available: {sorted(schema_cols)}"
                )

        # ── Step 4-5: Build + execute query ──────────────────────────────────
        rows, truncated = await _execute_query(
            conn_row=conn_row,
            entity_row=entity_row,
            select_fields=select_fields,
            filters=request.filters,
            sort=request.sort,
            limit=min(request.limit, MAX_QUERY_LIMIT),
        )

        # ── Step 6: Audit ─────────────────────────────────────────────────────
        await _write_audit(
            db=db,
            audit_id=audit_id,
            tenant_id=tenant_id,
            role_key=role_key,
            connection_id=connection_id,
            entity_id=entity_id,
            entity_name=entity_name,
            semantic_concept=semantic_concept,
            requested_fields=select_fields,
            filter_count=len(request.filters),
            result_count=len(rows),
            success=True,
        )

        source_label = f"{conn_row.display_name} / {entity_row.entity_name}"
        return CompanyDataQueryResponse(
            tenant_id=tenant_id,
            connection_id=connection_id,
            entity_name=entity_name,
            semantic_concept=semantic_concept,
            fields_returned=select_fields,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            sources=[source_label],
        )

    except Exception as exc:
        # Audit the failure too
        await _write_audit(
            db=db,
            audit_id=audit_id,
            tenant_id=tenant_id,
            role_key=role_key,
            connection_id=connection_id,
            entity_id=entity_id,
            entity_name=entity_name,
            semantic_concept=semantic_concept,
            requested_fields=request.fields,
            filter_count=len(request.filters),
            result_count=0,
            success=False,
            error_message=str(exc)[:400],
        )
        raise


# ── Resolve entity ────────────────────────────────────────────────────────────

async def _resolve_entity(
    request: CompanyDataQueryRequest,
    tenant_id: str,
    db: AsyncSession,
) -> tuple[DataConnection, SchemaEntity, list[str]]:
    """
    Returns (connection, entity, resolved_fields).
    Raises PermissionError on tenant mismatch.
    Raises ValueError if entity cannot be found.
    """
    resolved_fields = list(request.fields)

    if request.semantic_concept:
        # Resolve via semantic mapping
        mapping_result = await db.execute(
            select(SemanticMapping).where(
                SemanticMapping.tenant_id == tenant_id,
                SemanticMapping.semantic_concept == request.semantic_concept,
            )
        )
        mappings = mapping_result.scalars().all()
        if not mappings:
            raise ValueError(
                f"No semantic mapping found for concept '{request.semantic_concept}'. "
                "Create mappings via the Semantic Data Mapping panel first."
            )

        # All mappings for this concept must point to the same connection+entity
        connection_ids = {m.connection_id for m in mappings}
        entity_ids = {m.entity_id for m in mappings}
        if len(connection_ids) > 1 or len(entity_ids) > 1:
            raise ValueError(
                f"Semantic concept '{request.semantic_concept}' maps to multiple entities. "
                "Each concept must map to exactly one entity."
            )

        conn_id = mappings[0].connection_id
        ent_id = mappings[0].entity_id

        # If no fields requested, use the mapped fields
        if not resolved_fields:
            resolved_fields = [m.field_name for m in mappings]

    elif request.connection_id and request.entity_id:
        conn_id = request.connection_id
        ent_id = request.entity_id
    else:
        raise ValueError(
            "Either 'semantic_concept' or both 'connection_id' and 'entity_id' must be provided."
        )

    # Load and verify connection (tenant isolation)
    conn_result = await db.execute(
        select(DataConnection).where(
            DataConnection.id == conn_id,
            DataConnection.tenant_id == tenant_id,
        )
    )
    conn_row = conn_result.scalar_one_or_none()
    if not conn_row:
        raise PermissionError(
            f"Connection '{conn_id}' not found or does not belong to this tenant."
        )

    # Load and verify entity (tenant isolation)
    entity_result = await db.execute(
        select(SchemaEntity).where(
            SchemaEntity.id == ent_id,
            SchemaEntity.tenant_id == tenant_id,
            SchemaEntity.connection_id == conn_id,
        )
    )
    entity_row = entity_result.scalar_one_or_none()
    if not entity_row:
        raise PermissionError(
            f"Entity '{ent_id}' not found or does not belong to this connection/tenant."
        )

    return conn_row, entity_row, resolved_fields


# ── Execute query ─────────────────────────────────────────────────────────────

async def _execute_query(
    conn_row: DataConnection,
    entity_row: SchemaEntity,
    select_fields: list[str],
    filters: list[QueryFilter],
    sort: list[QuerySort],
    limit: int,
) -> tuple[list[dict], bool]:
    """
    Build a safe, parameterized SELECT and execute it against the external DB.
    Returns (rows, truncated).
    Credentials are decrypted here and discarded immediately after use.
    """
    # Build SQL using only validated identifiers — values are parameterized
    schema_prefix = (
        f'"{entity_row.schema_name}".' if entity_row.schema_name not in ("", "public") else ""
    )
    qualified_table = f'{schema_prefix}"{entity_row.entity_name}"'

    # SELECT clause — identifiers are quoted, not interpolated as values
    col_list = ", ".join(f'"{f}"' for f in select_fields)
    sql = f"SELECT {col_list} FROM {qualified_table}"

    # WHERE clause — values bound as parameters
    params: dict[str, object] = {}
    where_parts: list[str] = []
    for i, flt in enumerate(filters):
        col = f'"{flt.field}"'
        param_key = f"p{i}"
        op = flt.operator  # already validated to ALLOWED_OPERATORS
        if op in ("IS NULL", "IS NOT NULL"):
            where_parts.append(f"{col} {op}")
        elif op == "LIKE":
            params[param_key] = flt.value
            where_parts.append(f"{col} LIKE :{param_key}")
        elif op == "NOT LIKE":
            params[param_key] = flt.value
            where_parts.append(f"{col} NOT LIKE :{param_key}")
        else:
            params[param_key] = flt.value
            where_parts.append(f"{col} {op} :{param_key}")

    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    # ORDER BY
    if sort:
        order_parts = [f'"{s.field}" {s.direction}' for s in sort]
        sql += " ORDER BY " + ", ".join(order_parts)

    # LIMIT — fetch limit+1 to detect truncation
    fetch_limit = limit + 1
    sql += f" LIMIT {fetch_limit}"

    # Execute in a thread (sync DB drivers)
    password = decrypt_password(conn_row.encrypted_password)
    try:
        rows = await _run_query_sync(
            db_type=conn_row.db_type,
            host=conn_row.host,
            port=conn_row.port,
            database=conn_row.database_name,
            username=conn_row.username,
            password=password,
            ssl=conn_row.ssl_required,
            sql=sql,
            params=params,
        )
    finally:
        # Explicitly delete password from memory
        del password

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return rows, truncated


def _run_query_sync_blocking(
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    ssl: bool,
    sql: str,
    params: dict,
) -> list[dict]:
    """Synchronous query execution — runs in a thread executor."""
    if db_type == "postgresql":
        try:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras  # type: ignore[import]
            conn = psycopg2.connect(
                host=host, port=port, dbname=database,
                user=username, password=password,
                sslmode="require" if ssl else "disable",
                connect_timeout=15,
                options="-c default_transaction_read_only=on",  # force read-only
            )
            conn.autocommit = True
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Convert :name params to %(name)s for psycopg2
                pg_sql = sql
                pg_params: dict = {}
                for k, v in params.items():
                    pg_sql = pg_sql.replace(f":{k}", f"%({k})s")
                    pg_params[k] = v
                cur.execute(pg_sql, pg_params)
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        except ImportError:
            raise RuntimeError(
                "psycopg2 is not installed. Install it with: pip install psycopg2-binary"
            )

    elif db_type == "mysql":
        try:
            import mysql.connector  # type: ignore[import]
            conn = mysql.connector.connect(
                host=host, port=port, database=database,
                user=username, password=password,
                ssl_disabled=not ssl,
                connection_timeout=15,
            )
            # Enforce read-only at session level
            cur = conn.cursor(dictionary=True)
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            try:
                # Convert :name params to %(name)s for mysql.connector
                my_sql = sql
                my_params: dict = {}
                for k, v in params.items():
                    my_sql = my_sql.replace(f":{k}", f"%({k})s")
                    my_params[k] = v
                cur.execute(my_sql, my_params)
                return cur.fetchall()
            finally:
                conn.close()
        except ImportError:
            raise RuntimeError(
                "mysql-connector-python is not installed. Install with: pip install mysql-connector-python"
            )
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")


async def _run_query_sync(
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    ssl: bool,
    sql: str,
    params: dict,
) -> list[dict]:
    """Run the blocking query in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _run_query_sync_blocking,
        db_type, host, port, database, username, password, ssl, sql, params,
    )


# ── Audit writer ──────────────────────────────────────────────────────────────

async def _write_audit(
    db: AsyncSession,
    audit_id: str,
    tenant_id: str,
    role_key: str,
    connection_id: str | None,
    entity_id: str | None,
    entity_name: str | None,
    semantic_concept: str | None,
    requested_fields: list[str],
    filter_count: int,
    result_count: int,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Write a DataAccessAudit record. Never stores credentials or raw SQL."""
    try:
        audit = DataAccessAudit(
            id=audit_id,
            tenant_id=tenant_id,
            role_key=role_key,
            connection_id=connection_id,
            entity_id=entity_id,
            entity_name=entity_name,
            semantic_concept=semantic_concept,
            requested_fields_json=json.dumps(requested_fields[:30]),
            filter_count=filter_count,
            result_count=result_count,
            success=success,
            error_message=error_message,
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit)
        await db.flush()
    except Exception as exc:
        logger.error("Failed to write data access audit: %s", exc)
