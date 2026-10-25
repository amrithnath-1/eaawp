"""
EAAWP Document Processing Service

Pipeline:
    raw file bytes
        ↓ extract_text()   — format-aware text extraction
        ↓ chunk_text()     — RecursiveCharacterTextSplitter (no tiktoken)
        ↓ embed_texts_for_indexing() — Gemini embeddings, paced under the per-minute quota
        ↓ store_chunks()   — persist to document_chunks table
        ↓ mark_indexed()   — update knowledge_documents.status = "indexed"

Supported formats: PDF, DOCX, TXT, CSV, XLSX

Security notes
--------------
- Files are stored to a sandboxed uploads/ directory under the backend.
  The storage path is never exposed to the frontend.
- Tenant isolation: every DocumentChunk carries the document's tenant_id.
- If extraction or embedding fails, the document is marked "failed" with
  an error message. It is NOT marked searchable until indexing succeeds.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, KnowledgeDocument
from app.services.vector_store import embed_texts_for_indexing

logger = logging.getLogger(__name__)

# Upload directory — stored relative to backend root. UPLOAD_DIR overrides it.
# On Vercel the deployed code is read-only and only /tmp is writable; files
# there do not survive the function instance.
_DEFAULT_UPLOAD_DIR = (
    Path("/tmp/eaawp-uploads") if os.environ.get("VERCEL")
    else Path(__file__).parent.parent.parent / "uploads"
)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or _DEFAULT_UPLOAD_DIR)
# Upload directory — stored relative to backend root. UPLOAD_DIR overrides it
# (for example a mounted persistent disk on a hosting provider).
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or Path(__file__).parent.parent.parent / "uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Chunking parameters
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MAX_EXTRACTED_CHARS = 2_000_000   # bounds embedding cost/time for a single document


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(file_bytes: bytes, doc_type: str, filename: str) -> str:
    """
    Extract plain text from uploaded file bytes.
    Returns an empty string if extraction yields nothing.
    Raises ValueError for unsupported formats.
    """
    ext = doc_type.lower()

    if ext == "pdf":
        import pypdf  # type: ignore[import]
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
        return "\n\n".join(parts)

    if ext == "docx":
        import docx as _docx  # type: ignore[import]
        doc = _docx.Document(io.BytesIO(file_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if ext == "txt":
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="replace")

    if ext == "csv":
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [", ".join(row) for row in reader]
        return "\n".join(rows)

    if ext == "xlsx":
        import openpyxl  # type: ignore[import]
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        parts = []
        for sheet in wb.worksheets:
            sheet_rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                sheet_rows.append(", ".join(cells))
            parts.append(f"[Sheet: {sheet.title}]\n" + "\n".join(sheet_rows))
        return "\n\n".join(parts)

    raise ValueError(f"Unsupported document type: {ext}")


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks using character-based splitting (no tiktoken)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


# ── Full processing pipeline ──────────────────────────────────────────────────

async def process_document(
    doc_id: str,
    db: AsyncSession,
    openai_client: object = None,  # kept for call-site compatibility, not used
) -> None:
    """
    Background task: load the document record, read the file, extract text,
    chunk, embed using Gemini, store chunks, and mark the document as indexed.

    All errors are caught and stored in doc.error_message; the document
    is marked "failed" rather than leaving it in an unknown state.

    The openai_client parameter is accepted for backward compatibility but
    is NOT used — embeddings now come from the Gemini API.
    """
    # Load document record
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        logger.error("process_document: doc %s not found", doc_id)
        return

    doc.status = "processing"
    await db.flush()

    try:
        # Read file
        storage_path = Path(doc.storage_path)
        if not storage_path.exists():
            raise FileNotFoundError(f"Storage file missing: {storage_path}")
        file_bytes = storage_path.read_bytes()

        # Extract text
        text = extract_text(file_bytes, doc.doc_type, doc.name)
        if not text.strip():
            raise ValueError("No text could be extracted from this document.")
        if len(text) > MAX_EXTRACTED_CHARS:
            raise ValueError(
                f"Document text is too large to index ({len(text):,} characters; limit {MAX_EXTRACTED_CHARS:,}). "
                "Split it into smaller documents."
            )

        # Chunk
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Text could not be split into chunks.")

        # Embed using Gemini, paced under the per-minute quota with retries on 429
        all_embeddings = await embed_texts_for_indexing(chunks)

        # Delete any existing chunks for this document (re-processing)
        existing = await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )
        for old_chunk in existing.scalars().all():
            await db.delete(old_chunk)

        # Store new chunks
        for idx, (chunk_text_val, embedding) in enumerate(zip(chunks, all_embeddings)):
            chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                tenant_id=doc.tenant_id,
                chunk_index=idx,
                text=chunk_text_val,
                embedding_json=json.dumps(embedding),
                role_scope=doc.role_scope,
            )
            db.add(chunk)

        # Mark indexed
        doc.chunk_count = len(chunks)
        doc.status = "indexed"
        doc.indexed_at = datetime.now(timezone.utc)
        doc.error_message = None

        await db.flush()
        logger.info(
            "Document %s indexed: %d chunks (%s, tenant %s)",
            doc_id, len(chunks), doc.name, doc.tenant_id,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("Document %s processing failed: %s", doc_id, exc)
        doc.status = "failed"
        doc.error_message = str(exc)[:500]
        await db.flush()


def save_upload(file_bytes: bytes, tenant_id: str, filename: str) -> str:
    """
    Save uploaded bytes to a tenant-scoped directory inside UPLOAD_DIR.
    Returns the absolute storage path string (never exposed to the frontend).

    Security: the filesystem name is a UUID + validated extension only.
    The client-supplied filename is used solely to extract the extension
    (already validated against ALLOWED_EXTENSIONS in the router) and is
    NOT used as any part of the on-disk path, preventing directory traversal.
    """
    # Extract only the extension from the client filename — the basename is
    # discarded entirely.  The extension was already validated by the router.
    suffix = Path(filename).suffix.lower()  # e.g. ".pdf", ".docx"
    # Reject extensions with path separators or null bytes just in case.
    if "/" in suffix or "\\" in suffix or "\x00" in suffix:
        raise ValueError("Invalid file extension in upload filename")

    tenant_dir = UPLOAD_DIR / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the resolved tenant_dir is actually inside UPLOAD_DIR.
    try:
        tenant_dir.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError as exc:
        raise ValueError("Upload path escapes the upload directory") from exc

    safe_name = f"{uuid.uuid4()}{suffix}"
    dest = tenant_dir / safe_name

    # Double-check destination is inside tenant_dir (belt-and-suspenders).
    try:
        dest.resolve().relative_to(tenant_dir.resolve())
    except ValueError as exc:
        raise ValueError("Destination path escapes the tenant upload directory") from exc

    dest.write_bytes(file_bytes)
    return str(dest)
