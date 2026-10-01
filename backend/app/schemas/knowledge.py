"""
EAAWP Knowledge Base Schemas

HTTP boundary schemas for the Company Knowledge / RAG layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Document record ───────────────────────────────────────────────────────────

DocumentStatus = Literal["uploading", "processing", "indexed", "failed"]

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "csv", "xlsx"}


class KnowledgeDocumentOut(BaseModel):
    """A knowledge document record as returned from the API."""
    id: str
    tenant_id: str
    name: str
    doc_type: str          # pdf / docx / txt / csv / xlsx
    size_bytes: int
    access_level: str      # "All staff" | "Managers" | "Admins" | "AI only"
    role_scope: str        # which AI role may retrieve this document
    status: DocumentStatus
    error_message: str | None
    chunk_count: int
    uploaded_by: str
    uploaded_at: datetime
    indexed_at: datetime | None

    model_config = {"from_attributes": True}


class KnowledgeStatusOut(BaseModel):
    """Aggregate knowledge base status for a tenant."""
    documents_indexed: int
    documents_total: int
    documents_failed: int
    documents_processing: int
    last_indexed_at: datetime | None


# ── Retrieval ─────────────────────────────────────────────────────────────────

class RetrievalRequest(BaseModel):
    """Request body for POST /api/v1/knowledge/retrieve."""
    query: str = Field(..., min_length=1, max_length=2000)
    role_scope: str = Field(default="DIGITAL_MARKETING_MANAGER",
        description="Only return documents accessible to this role.")
    top_k: int = Field(default=4, ge=1, le=20)


class RetrievedChunk(BaseModel):
    """A single retrieved text chunk with source metadata."""
    chunk_id: str
    document_id: str
    document_name: str
    doc_type: str
    role_scope: str
    text: str
    score: float           # cosine similarity score 0..1


class RetrievalResponse(BaseModel):
    """Response from POST /api/v1/knowledge/retrieve."""
    query: str
    chunks: list[RetrievedChunk]
    total_found: int
