"""
EAAWP Knowledge Base Router

POST /api/v1/knowledge/upload          — upload a document (multipart/form-data)
GET  /api/v1/knowledge/documents       — list documents for this tenant
GET  /api/v1/knowledge/documents/{id}  — get one document record
DELETE /api/v1/knowledge/documents/{id} — delete document + chunks
GET  /api/v1/knowledge/status          — aggregate status
POST /api/v1/knowledge/retrieve        — semantic retrieval (agents only)

All endpoints require X-Tenant-ID header.
The retrieval endpoint additionally requires a role_scope to enforce
permission filtering before any content reaches the caller.

Security
--------
- Company A can never retrieve Company B's documents.
- Documents are only searchable when status == "indexed".
- Storage paths are never exposed in API responses.
- File bytes are never returned through the API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_current_user
from app.db.models import DocumentChunk, KnowledgeDocument, User
from app.db.session import get_db
from app.schemas.knowledge import (
    ALLOWED_EXTENSIONS,
    KnowledgeDocumentOut,
    KnowledgeStatusOut,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
)
from app.services.document_processor import process_document, save_upload
from app.services.vector_store import retrieve_similar_chunks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _get_openai_client():  # type: ignore[return]
    """Create an AsyncOpenAI client from config. Imported lazily to avoid startup cost."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=settings.openai_api_key)


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=KnowledgeDocumentOut,
    status_code=202,
    summary="Upload a company knowledge document for indexing",
)
async def upload_document(
    file: UploadFile = File(...),
    access_level: str = Form(default="All staff"),
    role_scope: str = Form(default="Global / Shared"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentOut:
    tenant_id = current_user.tenant_id
    uploaded_by = current_user.email or current_user.id
    # Validate extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")
    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Enforce size limit while streaming — reject before buffering the entire
    # payload into memory.  This prevents a large upload from exhausting RAM.
    chunks: list[bytes] = []
    received = 0
    async for chunk in file:
        received += len(chunk)
        if received > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_FILE_SIZE // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    # Validate access_level
    valid_access = {"All staff", "Managers", "Admins", "AI only"}
    if access_level not in valid_access:
        raise HTTPException(status_code=400, detail=f"access_level must be one of {sorted(valid_access)}")

    # Save file to disk
    storage_path = save_upload(file_bytes, tenant_id, file.filename)

    # Create metadata record
    doc = KnowledgeDocument(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=file.filename,
        doc_type=ext,
        size_bytes=len(file_bytes),
        storage_path=storage_path,
        access_level=access_level,
        role_scope=role_scope,
        status="processing",
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    await db.flush()
    doc_id = doc.id

    # Kick off processing as a background task
    # We pass a separate DB session for the background task to avoid
    # sharing the request-scoped session across async boundaries.
    asyncio.create_task(
        _process_in_background(doc_id, tenant_id)
    )

    return KnowledgeDocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        name=doc.name,
        doc_type=doc.doc_type,
        size_bytes=doc.size_bytes,
        access_level=doc.access_level,
        role_scope=doc.role_scope,
        status=doc.status,  # type: ignore[arg-type]
        error_message=doc.error_message,
        chunk_count=doc.chunk_count,
        uploaded_by=doc.uploaded_by,
        uploaded_at=doc.uploaded_at,
        indexed_at=doc.indexed_at,
    )


async def _process_in_background(doc_id: str, tenant_id: str) -> None:
    """Run document processing in a new DB session (background task).
    Embeddings are handled by Gemini inside process_document — no OpenAI
    client is required here.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            await process_document(doc_id, session)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("Background processing failed for doc %s: %s", doc_id, exc)


# ── List documents ────────────────────────────────────────────────────────────

@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentOut],
    summary="List knowledge documents for this tenant",
)
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeDocumentOut]:
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.tenant_id == current_user.tenant_id)
        .order_by(KnowledgeDocument.uploaded_at.desc())
    )
    docs = result.scalars().all()
    return [_doc_to_schema(d) for d in docs]


# ── Get one document ──────────────────────────────────────────────────────────

@router.get(
    "/documents/{doc_id}",
    response_model=KnowledgeDocumentOut,
    summary="Get a single knowledge document record",
)
async def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentOut:
    doc = await _get_doc_or_404(doc_id, current_user.tenant_id, db)
    return _doc_to_schema(doc)


# ── Delete document ───────────────────────────────────────────────────────────

@router.delete(
    "/documents/{doc_id}",
    status_code=200,
    summary="Delete a knowledge document and all its chunks",
)
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    doc = await _get_doc_or_404(doc_id, current_user.tenant_id, db)

    # Delete file from disk
    try:
        path = Path(doc.storage_path)
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("Could not delete file for doc %s: %s", doc_id, exc)

    await db.delete(doc)
    await db.flush()
    return {"deleted": doc_id}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get(
    "/status",
    response_model=KnowledgeStatusOut,
    summary="Get aggregate knowledge base status for this tenant",
)
async def knowledge_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeStatusOut:
    tenant_id = current_user.tenant_id
    result = await db.execute(
        select(
            KnowledgeDocument.status,
            func.count(KnowledgeDocument.id).label("cnt"),
        )
        .where(KnowledgeDocument.tenant_id == tenant_id)
        .group_by(KnowledgeDocument.status)
    )
    rows = result.fetchall()
    counts: dict[str, int] = {r.status: r.cnt for r in rows}

    # Last indexed_at
    last_result = await db.execute(
        select(func.max(KnowledgeDocument.indexed_at))
        .where(KnowledgeDocument.tenant_id == tenant_id)
    )
    last_indexed = last_result.scalar_one_or_none()

    return KnowledgeStatusOut(
        documents_indexed=counts.get("indexed", 0),
        documents_total=sum(counts.values()),
        documents_failed=counts.get("failed", 0),
        documents_processing=counts.get("processing", 0) + counts.get("uploading", 0),
        last_indexed_at=last_indexed,
    )


# ── Retrieve ──────────────────────────────────────────────────────────────────

@router.post(
    "/retrieve",
    response_model=RetrievalResponse,
    summary="Semantic retrieval from the knowledge base (for agents)",
)
async def retrieve(
    body: RetrievalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RetrievalResponse:
    tenant_id = current_user.tenant_id
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured.")

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        scored_chunks = await retrieve_similar_chunks(
            query=body.query,
            tenant_id=tenant_id,
            role_scope=body.role_scope,
            db=db,
            openai_client=client,
            top_k=body.top_k,
        )
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc)
        raise HTTPException(status_code=503, detail="Knowledge retrieval temporarily unavailable.") from exc

    if not scored_chunks:
        return RetrievalResponse(query=body.query, chunks=[], total_found=0)

    # Enrich with document metadata
    doc_ids = list({c.document_id for c in scored_chunks})
    doc_result = await db.execute(
        select(KnowledgeDocument.id, KnowledgeDocument.name, KnowledgeDocument.doc_type)
        .where(
            KnowledgeDocument.id.in_(doc_ids),
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.status == "indexed",
        )
    )
    doc_meta = {r.id: (r.name, r.doc_type) for r in doc_result.fetchall()}

    # Only return chunks from documents that are still indexed and in tenant
    output_chunks: list[RetrievedChunk] = []
    for sc in scored_chunks:
        if sc.document_id not in doc_meta:
            continue  # doc was deleted or not indexed
        name, dtype = doc_meta[sc.document_id]
        output_chunks.append(RetrievedChunk(
            chunk_id=sc.chunk_id,
            document_id=sc.document_id,
            document_name=name,
            doc_type=dtype,
            role_scope=sc.role_scope,
            text=sc.text,
            score=round(sc.score, 4),
        ))

    return RetrievalResponse(
        query=body.query,
        chunks=output_chunks,
        total_found=len(output_chunks),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_doc_or_404(
    doc_id: str, tenant_id: str, db: AsyncSession
) -> KnowledgeDocument:
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.tenant_id == tenant_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


def _doc_to_schema(doc: KnowledgeDocument) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        name=doc.name,
        doc_type=doc.doc_type,
        size_bytes=doc.size_bytes,
        access_level=doc.access_level,
        role_scope=doc.role_scope,
        status=doc.status,  # type: ignore[arg-type]
        error_message=doc.error_message,
        chunk_count=doc.chunk_count,
        uploaded_by=doc.uploaded_by,
        uploaded_at=doc.uploaded_at,
        indexed_at=doc.indexed_at,
    )
