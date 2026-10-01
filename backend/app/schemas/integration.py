"""
EAAWP Data Integration Schemas

HTTP boundary shapes for the Company Data Integration layer.
Passwords are accepted on CREATE but NEVER returned in any response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── Column metadata ───────────────────────────────────────────────────────────

class ColumnMetaOut(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool


# ── Schema entity ─────────────────────────────────────────────────────────────

class SchemaEntityOut(BaseModel):
    id: str
    connection_id: str
    schema_name: str
    entity_name: str
    entity_type: str
    columns: list[ColumnMetaOut]
    row_count_estimate: int | None
    is_allowed: bool
    discovered_at: datetime

    model_config = {"from_attributes": True}


# ── Data connection ───────────────────────────────────────────────────────────

ConnectionStatus = Literal["not_tested", "testing", "connected", "failed"]

SUPPORTED_DB_TYPES = {"postgresql", "mysql"}


class DataConnectionOut(BaseModel):
    """
    Connection record returned to the frontend.
    encrypted_password is excluded — never serialised.
    """
    id: str
    tenant_id: str
    display_name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    ssl_required: bool
    status: ConnectionStatus
    last_tested_at: datetime | None
    error_message: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    entity_count: int = 0          # populated from join in the router
    allowed_entity_count: int = 0

    model_config = {"from_attributes": True}


class DataConnectionCreate(BaseModel):
    """Request body for creating a new connection. Password required here only."""
    display_name: str = Field(..., min_length=1, max_length=255)
    db_type: str = Field(..., description="postgresql | mysql")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(..., min_length=1, max_length=255)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, description="Encrypted at rest — never returned")
    ssl_required: bool = True
    created_by: str = "admin"

    @field_validator("db_type")
    @classmethod
    def validate_db_type(cls, v: str) -> str:
        if v.lower() not in SUPPORTED_DB_TYPES:
            raise ValueError(f"db_type must be one of {sorted(SUPPORTED_DB_TYPES)}")
        return v.lower()


class DataConnectionUpdate(BaseModel):
    """Partial update — all fields optional. Password update requires explicit field."""
    display_name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = None
    username: str | None = None
    password: str | None = Field(default=None, description="Provide to rotate credentials")
    ssl_required: bool | None = None


# ── Test result ───────────────────────────────────────────────────────────────

class ConnectionTestResponse(BaseModel):
    connection_id: str
    success: bool
    status: ConnectionStatus
    server_version: str | None
    error_message: str | None


# ── Permission update ─────────────────────────────────────────────────────────

class EntityPermissionUpdate(BaseModel):
    """Allow or deny an entity."""
    is_allowed: bool


class BulkEntityPermissionUpdate(BaseModel):
    """Set permissions for multiple entities at once."""
    entity_ids: list[str]
    is_allowed: bool
