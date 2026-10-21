"""
EAAWP Vector Store Abstraction

Clean interface over vector storage so the implementation can be swapped
(SQLite JSON → pgvector → Chroma → Pinecone) without touching the retrieval
service or the agent engine.

Current implementation: SQLite + numpy cosine similarity.
- Embeddings stored as JSON float arrays in document_chunks.embedding_json.
- Retrieval loads all tenant-scoped, permission-filtered chunks and ranks by
  cosine similarity in Python. Suitable for development and small corpora.
- For production: implement PostgresVectorStore using pgvector.

Embedding provider: Google Gemini (langchain-google-genai).
- Model: models/gemini-embedding-001  (3072 dimensions)
- Both indexing and retrieval use the same model and key.
- OPENAI_API_KEY is NOT required for document search.

Security contract
-----------------
Every operation is scoped to (tenant_id, role_scope).
Cross-tenant retrieval is structurally impossible — tenant_id is always
an explicit filter parameter, never derived from the query text.

Dimension mismatch guard
------------------------
If the stored embedding dimension differs from the current model's output,
the chunk is silently skipped (score=0) and a warning is logged.
This prevents crashes when re-indexing is in progress.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, KnowledgeDocument

logger = logging.getLogger(__name__)

# ── Embedding model configuration ────────────────────────────────────────────
# Uses Google Gemini embeddings — no OpenAI key required.
# Override via GEMINI_EMBEDDING_MODEL environment variable.
# WARNING: changing this model after documents are indexed requires full
#          re-indexing of all existing DocumentChunk rows.

from app.config import settings as _settings

GEMINI_EMBEDDING_MODEL: str = getattr(
    _settings, "gemini_embedding_model", "models/gemini-embedding-2"
)
EMBEDDING_DIM = 3072  # dimensions for gemini-embedding-2 and gemini-embedding-001

# Keep EMBEDDING_MODEL alias for backwards compatibility with any code that
# imports the old name.
EMBEDDING_MODEL = GEMINI_EMBEDDING_MODEL


# ── Embedding client factory ──────────────────────────────────────────────────

def _make_gemini_embedder() -> Any:
    """Build a GoogleGenerativeAIEmbeddings instance using the configured key."""
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    import os

    api_key = os.environ.get("GEMINI_API_KEY", _settings.gemini_api_key)
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in backend/.env to enable document search."
        )
    return GoogleGenerativeAIEmbeddings(
        model=GEMINI_EMBEDDING_MODEL,
        google_api_key=api_key,
    )


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    document_name: str
    doc_type: str
    role_scope: str
    text: str
    score: float


# ── Embedding helpers ─────────────────────────────────────────────────────────

async def embed_texts_gemini(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using the Gemini Embeddings API (async-friendly).
    Returns a list of float vectors in the same order as the input.

    The GoogleGenerativeAIEmbeddings class is synchronous under the hood;
    we run it in an executor to avoid blocking the event loop.
    """
    if not texts:
        return []
    import asyncio

    embedder = _make_gemini_embedder()

    loop = asyncio.get_running_loop()
    # embed_documents is synchronous — offload to a thread pool
    vectors: list[list[float]] = await loop.run_in_executor(
        None, embedder.embed_documents, texts
    )
    return vectors


def embed_query_gemini_sync(query: str) -> list[float]:
    """
    Embed a single query string using Gemini Embeddings — synchronous version.
    Safe to call from synchronous contexts (e.g. LangChain @tool functions).
    Returns a float vector.
    """
    embedder = _make_gemini_embedder()
    return embedder.embed_query(query)  # sync call — no event loop needed


async def embed_query_gemini(query: str) -> list[float]:
    """
    Embed a single query string using Gemini Embeddings (async wrapper).
    Returns a float vector. Delegates to the sync version in a thread executor.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_query_gemini_sync, query)
# Old callers passed an AsyncOpenAI client; this wrapper ignores the client
# argument and uses Gemini instead.  The migration is transparent to callers
# that still pass a client object — the client is simply discarded.

async def embed_text(texts: list[str], client: Any = None) -> list[list[float]]:  # noqa: ANN001
    """
    Embed texts using Gemini.

    The `client` parameter is accepted for backward compatibility but is
    NOT used — Gemini credentials come from the environment.
    If OpenAI client is passed, it is silently ignored.
    """
    if client is not None:
        logger.debug(
            "embed_text: client argument ignored — using Gemini embeddings."
        )
    return await embed_texts_gemini(texts)


# ── Cosine similarity ─────────────────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return cosine similarity between two 1-D float vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Retrieval ─────────────────────────────────────────────────────────────────

ACCESS_LEVELS = ("All staff", "Managers", "Admins", "AI only")
MANAGER_ROLES = frozenset({"manager"})


def allowed_access_levels(user_role: str | None, is_admin: bool, human_direct: bool) -> list[str]:
    """
    Which document access levels the ASKER may read.
      All staff - everyone;  Managers - managers and admins;  Admins - admins only;
      AI only   - usable by the AI employee when answering (human_direct=False) but never browsable/retrievable by a person directly.
    An unknown asker (no user, e.g. an unattended run) gets the most conservative set.
    """
    levels = ["All staff"]
    if is_admin or (user_role or "").strip().lower() in MANAGER_ROLES:
        levels.append("Managers")
    if is_admin:
        levels.append("Admins")
    if not human_direct:
        levels.append("AI only")
    return levels


async def retrieve_similar_chunks(
    query: str,
    tenant_id: str,
    role_scope: str,
    db: AsyncSession,
    # client parameter kept for backward compatibility — ignored
    openai_client: Any = None,
    top_k: int = 4,
    access_levels: list[str] | None = None,
) -> list[ScoredChunk]:
    """
    Embed the query with Gemini and return the top-k most similar chunks.

    Security: only chunks where chunk.tenant_id == tenant_id AND
    chunk.role_scope is accessible to role_scope are returned.

    Role scope access rules:
    - "Global / Shared" chunks are accessible to ALL roles.
    - Role-specific chunks (e.g. "Sales Agent Only") are only accessible
      when role_scope matches.

    The openai_client parameter is kept for call-site backward compatibility
    but is not used — Gemini is always the embedding provider.

    access_levels: the document access levels the asker may read (see allowed_access_levels). None means
    the most conservative default (All staff only), never "everything".
    """
    levels = list(access_levels) if access_levels is not None else ["All staff"]
    query_vec_list = await embed_query_gemini(query)

    query_vec = np.array(query_vec_list, dtype=np.float32)
    accessible_scopes = _accessible_scopes(role_scope)

    result = await db.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.text,
            DocumentChunk.embedding_json,
            DocumentChunk.role_scope,
            KnowledgeDocument.name.label("doc_name"),
            KnowledgeDocument.doc_type.label("doc_type"),
        ).join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id).where(
            DocumentChunk.tenant_id == tenant_id,
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.status == "indexed",
            KnowledgeDocument.access_level.in_(levels),
            DocumentChunk.role_scope.in_(accessible_scopes),
        )
    )
    rows = result.fetchall()

    if not rows:
        return []

    scored: list[tuple[float, ScoredChunk]] = []
    for row in rows:
        embedding = json.loads(row.embedding_json or "[]")
        if not embedding:
            continue
        # Dimension mismatch guard — skip stale OpenAI chunks rather than crashing
        if len(embedding) != len(query_vec_list):
            logger.warning(
                "Skipping chunk %s: stored dim=%d, query dim=%d. "
                "Re-index documents after changing the embedding model.",
                row.id, len(embedding), len(query_vec_list),
            )
            continue
        chunk_vec = np.array(embedding, dtype=np.float32)
        score = _cosine_similarity(query_vec, chunk_vec)
        scored.append((score, ScoredChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_name=row.doc_name,
            doc_type=row.doc_type,
            role_scope=row.role_scope,
            text=row.text,
            score=score,
        )))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [sc for _, sc in scored[:top_k]]


VALID_ROLE_SCOPES = frozenset({
    "Global / Shared", "Sales Agent Only", "Finance Agent Only", "HR Agent Only", "Operations Agent Only", "Customer Service Agent Only",
})


def _accessible_scopes(role_scope: str) -> list[str]:
    """
    Return the list of role_scope values a given role may access.
    Global / Shared is always included.
    """
    base = ["Global / Shared"]
    scope_map = {
        "DIGITAL_MARKETING_MANAGER": "Sales Agent Only",
        "SALES_DEVELOPMENT_REP": "Sales Agent Only",
        "FINANCIAL_ANALYST": "Finance Agent Only",
        "HR_BUSINESS_PARTNER": "HR Agent Only",
        "OPERATIONS_ANALYST": "Operations Agent Only",
        "CUSTOMER_SUCCESS_MANAGER": "Customer Service Agent Only",
    }
    specific = scope_map.get(role_scope)
    if specific:
        base.append(specific)
    return base
