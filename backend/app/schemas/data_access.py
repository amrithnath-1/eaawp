"""
EAAWP Controlled Data Access Schemas

Request/response shapes for the query_company_data tool and the
semantic mapping management APIs.

Security invariants
-------------------
- No credentials or connection strings appear in any schema.
- Raw SQL is never accepted as input — the agent sends structured params.
- Allowed operators and sort directions are explicit whitelists.
- Maximum result limit is enforced server-side; clients cannot override it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Hard limits ───────────────────────────────────────────────────────────────

MAX_QUERY_LIMIT = 200          # max rows returned in a single query
DEFAULT_QUERY_LIMIT = 50
MAX_FIELDS = 30                # max columns requested in one call
MAX_FILTERS = 10

# Allowed filter operators — no raw SQL fragments
ALLOWED_OPERATORS = {"=", "!=", "<", "<=", ">", ">=", "LIKE", "NOT LIKE", "IS NULL", "IS NOT NULL"}
ALLOWED_SORT_DIRECTIONS = {"ASC", "DESC"}

# Identifier safety: only alphanum + underscore + dot (for schema.table)
import re
_SAFE_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*$')


def validate_identifier(v: str, label: str = "identifier") -> str:
    """Raise ValueError if v is not a safe SQL identifier."""
    if not _SAFE_IDENTIFIER.match(v):
        raise ValueError(
            f"{label} '{v}' contains invalid characters. "
            "Only letters, digits, underscores and dots are allowed."
        )
    if len(v) > 128:
        raise ValueError(f"{label} must be 128 characters or fewer.")
    return v


# ── Filter ────────────────────────────────────────────────────────────────────

class QueryFilter(BaseModel):
    """A single WHERE clause condition using only whitelisted operators."""
    field: str = Field(..., min_length=1, max_length=128,
        description="Column name to filter on. Must exist in the entity.")
    operator: str = Field(...,
        description=f"Comparison operator. Allowed: {sorted(ALLOWED_OPERATORS)}")
    value: str | int | float | None = Field(
        default=None,
        description="Filter value. Ignored for IS NULL / IS NOT NULL operators.")

    @field_validator("field")
    @classmethod
    def validate_field(cls, v: str) -> str:
        return validate_identifier(v, "filter field")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_OPERATORS:
            raise ValueError(
                f"Operator '{v}' is not allowed. "
                f"Allowed operators: {sorted(ALLOWED_OPERATORS)}"
            )
        return upper


# ── Sort ──────────────────────────────────────────────────────────────────────

class QuerySort(BaseModel):
    """ORDER BY specification."""
    field: str = Field(..., min_length=1, max_length=128)
    direction: str = Field(default="ASC")

    @field_validator("field")
    @classmethod
    def validate_field(cls, v: str) -> str:
        return validate_identifier(v, "sort field")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ALLOWED_SORT_DIRECTIONS:
            raise ValueError(f"Sort direction must be ASC or DESC, got '{v}'")
        return upper


# ── Query request ─────────────────────────────────────────────────────────────

class CompanyDataQueryRequest(BaseModel):
    """
    Structured query request from the agent.
    No raw SQL — the backend translates this to a safe parameterized query.
    """
    # Route via semantic concept (preferred) OR direct entity reference
    semantic_concept: str | None = Field(
        default=None, max_length=128,
        description="Schema-independent concept name (e.g. 'campaign_performance'). "
                    "The backend resolves the actual entity and field mappings."
    )

    @field_validator("semantic_concept")
    @classmethod
    def validate_concept(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_identifier(v, "semantic_concept")
    connection_id: str | None = Field(
        default=None,
        description="Explicit connection ID. Required when semantic_concept is not provided."
    )
    entity_id: str | None = Field(
        default=None,
        description="Explicit entity ID. Required when semantic_concept is not provided."
    )

    # What to retrieve
    fields: list[str] = Field(
        default_factory=list,
        description="Column names to return. Empty list returns all allowed columns."
    )
    filters: list[QueryFilter] = Field(default_factory=list)
    sort: list[QuerySort] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_FIELDS:
            raise ValueError(f"Too many fields requested ({len(v)}). Maximum is {MAX_FIELDS}.")
        return [validate_identifier(f, "field") for f in v]

    @field_validator("filters")
    @classmethod
    def validate_filter_count(cls, v: list[QueryFilter]) -> list[QueryFilter]:
        if len(v) > MAX_FILTERS:
            raise ValueError(f"Too many filters ({len(v)}). Maximum is {MAX_FILTERS}.")
        return v


# ── Query response ────────────────────────────────────────────────────────────

class CompanyDataQueryResponse(BaseModel):
    """Result returned to the agent after a successful authorized query."""
    tenant_id: str
    connection_id: str
    entity_name: str
    semantic_concept: str | None
    fields_returned: list[str]
    rows: list[dict]          # list of {column: value} dicts
    row_count: int
    truncated: bool           # True if result was capped at limit
    sources: list[str]        # e.g. ["Marketing DB / ad_campaigns"]


# ── Semantic mapping ──────────────────────────────────────────────────────────

class SemanticMappingOut(BaseModel):
    id: str
    tenant_id: str
    semantic_concept: str
    connection_id: str
    entity_id: str
    field_name: str
    display_label: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SemanticMappingCreate(BaseModel):
    semantic_concept: str = Field(..., min_length=1, max_length=128)
    connection_id: str = Field(..., min_length=1)
    entity_id: str = Field(..., min_length=1)
    field_name: str = Field(..., min_length=1, max_length=255)
    display_label: str = Field(default="", max_length=255)
    created_by: str = Field(default="admin")

    @field_validator("semantic_concept", "field_name")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        return validate_identifier(v, "semantic concept / field name")


class SemanticMappingUpdate(BaseModel):
    display_label: str | None = None
    field_name: str | None = None

    @field_validator("field_name")
    @classmethod
    def validate_field(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_identifier(v, "field name")
