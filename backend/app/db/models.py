"""
EAAWP SQLAlchemy ORM models.

Multi-tenancy
-------------
Every data table carries a tenant_id column that references companies.id.
All queries MUST include a tenant_id filter. Tenant isolation is enforced
at the service/repository layer, not the database constraint layer.

Data-agnostic architecture
--------------------------
These models represent the EAAWP platform's own internal state.
They do NOT represent a company's business data (campaigns, leads, revenue, etc.)
That data lives in the company's own systems and is accessed only through
the Company Integration Layer (to be implemented separately).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Company (tenant root) ─────────────────────────────────────────────────────

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    region: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    employees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="company", lazy="noload")
    ai_employees: Mapped[list["AIEmployee"]] = relationship(
        "AIEmployee", back_populates="company", lazy="noload"
    )


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="Employee")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    company: Mapped["Company"] = relationship("Company", back_populates="users", lazy="noload")


# ── LLM Model ─────────────────────────────────────────────────────────────────

class LLMModel(Base):
    """Catalogue of LLM model definitions available in the platform."""

    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)   # e.g. "openai"
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "gpt-4o-mini"
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("provider", "model_name", name="uq_llm_provider_model"),)

    ai_employees: Mapped[list["AIEmployee"]] = relationship(
        "AIEmployee", back_populates="llm_model", lazy="noload"
    )


# ── AIEmployee ────────────────────────────────────────────────────────────────

class AIEmployee(Base):
    """
    A specialised AI agent deployed by a company.

    The role_key references the platform's internal role registry
    (e.g. DIGITAL_MARKETING_MANAGER). It does NOT reference any
    company-specific schema.
    """

    __tablename__ = "ai_employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    llm_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="IDLE")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    company: Mapped["Company"] = relationship(
        "Company", back_populates="ai_employees", lazy="noload"
    )
    llm_model: Mapped["LLMModel | None"] = relationship(
        "LLMModel", back_populates="ai_employees", lazy="noload"
    )
    configuration: Mapped["AgentConfiguration | None"] = relationship(
        "AgentConfiguration", back_populates="ai_employee", uselist=False, lazy="noload"
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="ai_employee", lazy="noload"
    )
    activity_events: Mapped[list["ActivityEvent"]] = relationship(
        "ActivityEvent", back_populates="ai_employee", lazy="noload"
    )
    insights: Mapped[list["Insight"]] = relationship(
        "Insight", back_populates="ai_employee", lazy="noload"
    )
    schedules: Mapped[list["Schedule"]] = relationship(
        "Schedule", back_populates="ai_employee", lazy="noload"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="ai_employee", lazy="noload"
    )


# ── AgentConfiguration ────────────────────────────────────────────────────────

class AgentConfiguration(Base):
    """
    Mutable configuration for a specific AIEmployee.
    Stored as JSON blobs for flexibility — the schema evolves without migrations.
    """

    __tablename__ = "agent_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_employees.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    system_persona: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(32), nullable=False, default="Concise")
    autonomy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # JSON-serialised dicts — avoids a separate join for simple key-value stores
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    tool_scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    ai_employee: Mapped["AIEmployee"] = relationship(
        "AIEmployee", back_populates="configuration", lazy="noload"
    )


# ── RoleConfiguration ─────────────────────────────────────────────────────────

class RoleConfiguration(Base):
    """
    Persistent, editable configuration for a role within a tenant.
    This is the layer between company intent and the AgentBlueprint.
    One row per (tenant_id, role_key) pair — unique constraint enforced.

    The execution flow is:
        RoleConfiguration → build_blueprint() → AgentBlueprint → DynamicAgentEngine
    """

    __tablename__ = "role_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Identity
    role_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Rich configuration — stored as JSON for schema flexibility
    responsibilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    objectives_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_persona: Mapped[str] = mapped_column(Text, nullable=False, default="")

    tool_scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    workflows_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    monitoring_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    communication_style: Mapped[str] = mapped_column(String(64), nullable=False, default="Concise")
    schedule_preferences_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    memory_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    llm_model: Mapped[str] = mapped_column(String(128), nullable=False, default="gpt-4o-mini")
    autonomy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    quick_prompts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "role_key", name="uq_role_config_tenant_role"),
    )


# ── ConfigChangeProposal ──────────────────────────────────────────────────────

class ConfigChangeProposal(Base):
    """
    Audit record for a natural-language configuration change proposal.

    Lifecycle:
        pending   → administrator sees the proposal
        approved  → patch applied to RoleConfiguration
        rejected  → discarded, configuration unchanged

    The actual diff is stored as JSON in patch_json so it can be replayed or
    audited without re-running the LLM.
    """

    __tablename__ = "config_change_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    original_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    interpreted_intent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_changes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    patch_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    validation_errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    validation_warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    approval_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # "pending" | "approved" | "rejected"
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── KnowledgeDocument ─────────────────────────────────────────────────────────

class KnowledgeDocument(Base):
    """
    Metadata record for a company-uploaded knowledge document.
    The actual file bytes are stored on disk (uploads/ folder).
    Vector embeddings for each chunk are stored in DocumentChunk.

    Status lifecycle:
        uploading → processing → indexed
                               → failed
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)   # pdf/docx/txt/csv/xlsx
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    access_level: Mapped[str] = mapped_column(String(32), nullable=False, default="All staff")
    role_scope: Mapped[str] = mapped_column(String(128), nullable=False, default="Global / Shared")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploading")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", lazy="noload",
        cascade="all, delete-orphan"
    )


# ── DocumentChunk ─────────────────────────────────────────────────────────────

class DocumentChunk(Base):
    """
    A single text chunk from a KnowledgeDocument, with its embedding
    stored as a JSON-serialised float list.

    Embeddings are stored inline (SQLite-friendly). For production with
    PostgreSQL, pgvector would replace this with a native vector column.
    The VectorStore abstraction in app/services/vector_store.py hides
    this detail from the retrieval service.
    """

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    role_scope: Mapped[str] = mapped_column(String(128), nullable=False, default="Global / Shared")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument", back_populates="chunks", lazy="noload"
    )


# ── DataConnection ────────────────────────────────────────────────────────────

class DataConnection(Base):
    """
    A company's external data source connection.
    Credentials are stored encrypted — the raw password/DSN is NEVER returned
    to the frontend or placed in any LLM prompt.

    One connection belongs to exactly one tenant. Tenant isolation is
    enforced on every query.

    Status lifecycle:
        not_tested → testing → connected → failed
    """

    __tablename__ = "data_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    db_type: Mapped[str] = mapped_column(String(32), nullable=False)   # "postgresql" | "mysql"
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=5432)
    database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Password stored as a fernet-encrypted blob — never returned in API responses
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ssl_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_tested"
    )  # not_tested | testing | connected | failed
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    schema_entities: Mapped[list["SchemaEntity"]] = relationship(
        "SchemaEntity", back_populates="connection", lazy="noload",
        cascade="all, delete-orphan"
    )


# ── SchemaEntity ──────────────────────────────────────────────────────────────

class SchemaEntity(Base):
    """
    Discovered metadata for one table/view/entity from a DataConnection.
    Stores only schema metadata — never actual company data rows.

    The administrator uses this to decide which entities the AI may access.
    """

    __tablename__ = "schema_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False, default="public")
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False, default="table")  # table | view
    # JSON array of {name, data_type, is_nullable, is_primary_key}
    columns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    row_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Whether the AI employee is allowed to access this entity
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    connection: Mapped["DataConnection"] = relationship(
        "DataConnection", back_populates="schema_entities", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint(
            "connection_id", "schema_name", "entity_name",
            name="uq_schema_entity_conn_schema_name"
        ),
    )


# ── SemanticMapping ───────────────────────────────────────────────────────────

class SemanticMapping(Base):
    """
    Maps a semantic concept name (schema-independent) to an actual entity
    field in a specific company data connection.

    This allows the DMM to think in business terms ('campaign_name', 'spend')
    while the platform resolves the actual table/column for that company.

    One SemanticMapping per (tenant_id, semantic_concept, connection_id, entity_id, field_name).
    """

    __tablename__ = "semantic_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The schema-independent concept the agent uses (e.g. "campaign_name")
    semantic_concept: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Which connection + entity + field this concept maps to
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_connections.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schema_entities.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional human-readable label
    display_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "semantic_concept", "connection_id", "entity_id", "field_name",
            name="uq_semantic_mapping_concept_field"
        ),
    )


# ── DataAccessAudit ───────────────────────────────────────────────────────────

class DataAccessAudit(Base):
    """
    Audit record for every data access request made by an AI agent.
    Contains safe metadata only — no credentials, no raw SQL, no sensitive row data.
    """

    __tablename__ = "data_access_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    semantic_concept: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    filter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# ── ExecutionPlan ─────────────────────────────────────────────────────────────

class ExecutionPlan(Base):
    """
    Persistent execution plan for multi-step agent tasks.
    Stores safe execution metadata — NO chain-of-thought, NO credentials.

    Status lifecycle:
        planning → running → completed
                           → failed
                           → awaiting_approval (paused for action approval)
                           → rejected
    """

    __tablename__ = "execution_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)     # user's request
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="planning")
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Serialised blueprint snapshot for permission revalidation on resume
    blueprint_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan_steps: Mapped[list["PlanStep"]] = relationship(
        "PlanStep", back_populates="plan", lazy="noload",
        cascade="all, delete-orphan", order_by="PlanStep.step_index"
    )


# ── PlanStep ──────────────────────────────────────────────────────────────────

class PlanStep(Base):
    """
    A single step within an ExecutionPlan.
    Stores safe execution metadata — no credentials, no raw SQL.
    """

    __tablename__ = "plan_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("execution_plans.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_type: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_audit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["ExecutionPlan"] = relationship(
        "ExecutionPlan", back_populates="plan_steps", lazy="noload"
    )


# ── ActionAudit ───────────────────────────────────────────────────────────────

class ActionAudit(Base):
    """
    Audit record for every action tool request.
    Tracks the full lifecycle: proposed → approval → executed/rejected/failed.

    Security: arguments_json never stores credentials or arbitrary SQL.
    The framework validates inputs before storing them.
    """

    __tablename__ = "action_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Safe serialised arguments — never contains credentials
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    # approval_status: proposed | approved | rejected
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    # execution_status: pending | executed | failed | skipped
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    approval_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Task ──────────────────────────────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    department: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    required_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    ai_employee: Mapped["AIEmployee"] = relationship(
        "AIEmployee", back_populates="tasks", lazy="noload"
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        "ApprovalRequest", back_populates="task", lazy="noload"
    )


# ── ActivityEvent ─────────────────────────────────────────────────────────────

class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    ai_employee: Mapped["AIEmployee"] = relationship(
        "AIEmployee", back_populates="activity_events", lazy="noload"
    )


# ── Insight ───────────────────────────────────────────────────────────────────

class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    department: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ai_employee: Mapped["AIEmployee"] = relationship(
        "AIEmployee", back_populates="insights", lazy="noload"
    )


# ── Schedule ──────────────────────────────────────────────────────────────────

class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(128), nullable=False)
    next_run: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    owner: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    ai_employee: Mapped["AIEmployee"] = relationship(
        "AIEmployee", back_populates="schedules", lazy="noload"
    )


# ── ApprovalRequest ───────────────────────────────────────────────────────────

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, default="AI")
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task | None"] = relationship(
        "Task", back_populates="approval_requests", lazy="noload"
    )


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    ai_employee: Mapped["AIEmployee | None"] = relationship(
        "AIEmployee", back_populates="audit_logs", lazy="noload"
    )


# ── EmployeeBlueprintProposal ─────────────────────────────────────────────────

class EmployeeBlueprintProposalORM(Base):
    """
    Persisted AI Employee Blueprint Proposal — Phase H.

    Stores the LLM-generated proposal and tracks approval/rejection.
    The actual AIEmployee row is created only after approval.
    """

    __tablename__ = "employee_blueprint_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    responsibilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    objectives_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_integrations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allowed_tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    guarded_tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    suggested_schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    communication_style: Mapped[str] = mapped_column(String(32), nullable=False, default="Concise")
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-4o-mini")
    system_persona: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── Workflow ──────────────────────────────────────────────────────────────────

class Workflow(Base):
    """
    Persistent Workflow definition — Phase I.

    A workflow defines a recurring or triggered sequence of steps
    that an AI employee executes.
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── RefreshToken ──────────────────────────────────────────────────────────────

class RefreshToken(Base):
    """
    DB-persisted refresh token record for revocation support.

    The token_hash stores a SHA-256 hash of the JWT refresh token string —
    never the raw token. Comparison: hash(presented_token) == token_hash.

    On logout or revoke: set revoked=True.
    On new refresh: insert new record, optionally revoke the old one (rotation).

    Security:
    - Raw token never stored.
    - token_hash is not reversible.
    - jti (JWT ID) links the DB record to a JWT claim for fast lookup.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 hex digest of the raw JWT string — NOT the raw token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # jti claim from the JWT for fast lookup
    jti: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("jti", name="uq_refresh_token_jti"),
    )
