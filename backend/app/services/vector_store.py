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

Security contract
-----------------
Every operation is scoped to (tenant_id, role_scope).
Cross-tenant retrieval is structurally impossible — tenant_id is always
an explicit filter parameter, never derived from the query text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk

logger = logging.getLogger(__name__)

# Embedding model — read from settings, default to text-embedding-3-small
# Change via EMBEDDING_MODEL environment variable.
# WARNING: changing this after documents are indexed requires full re-indexing.
from app.config import settings as _settings
EMBEDDING_MODEL: str = _settings.embedding_model
EMBEDDING_DIM = 1536  # documentation constant — actual dim depends on the model


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    document_name: str
    doc_type: str
    role_scope: str
    text: str
    score: float


async def embed_text(texts: list[str], client: AsyncOpenAI) -> list[list[float]]:
    """
    Embed a list of texts using the OpenAI embeddings API.
    Returns a list of float vectors in the same order as the input.
    """
    if not texts:
        return []
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return cosine similarity between two 1-D float vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


async def retrieve_similar_chunks(
    query: str,
    tenant_id: str,
    role_scope: str,
    db: AsyncSession,
    openai_client: AsyncOpenAI,
    top_k: int = 4,
) -> list[ScoredChunk]:
    """
    Embed the query and return the top-k most similar chunks for the given
    tenant and role scope.

    Security: only chunks where chunk.tenant_id == tenant_id AND
    chunk.role_scope is accessible to role_scope are returned.

    Role scope access rules:
    - "Global / Shared" chunks are accessible to ALL roles.
    - Role-specific chunks (e.g. "Sales Agent Only") are only accessible
      when role_scope matches.
    """
    # Embed the query
    query_vecs = await embed_text([query], openai_client)
    if not query_vecs:
        return []
    query_vec = np.array(query_vecs[0], dtype=np.float32)

    # Load candidate chunks with permission filtering
    accessible_scopes = _accessible_scopes(role_scope)

    result = await db.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.text,
            DocumentChunk.embedding_json,
            DocumentChunk.role_scope,
        ).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.role_scope.in_(accessible_scopes),
        )
    )
    rows = result.fetchall()

    if not rows:
        return []

    # Score by cosine similarity
    scored: list[tuple[float, ScoredChunk]] = []
    for row in rows:
        embedding = json.loads(row.embedding_json or "[]")
        if not embedding:
            continue
        chunk_vec = np.array(embedding, dtype=np.float32)
        score = _cosine_similarity(query_vec, chunk_vec)
        scored.append((score, ScoredChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_name="",   # filled by caller from doc metadata
            doc_type="",
            role_scope=row.role_scope,
            text=row.text,
            score=score,
        )))

    # Sort descending by score, return top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    return [sc for _, sc in scored[:top_k]]


def _accessible_scopes(role_scope: str) -> list[str]:
    """
    Return the list of role_scope values a given role may access.
    Global / Shared is always included.
    """
    base = ["Global / Shared"]
    scope_map = {
        "DIGITAL_MARKETING_MANAGER": "Sales Agent Only",   # marketing uses sales scope too
        "SALES_DEVELOPMENT_REP": "Sales Agent Only",
        "FINANCIAL_ANALYST": "Finance Agent Only",
        "HR_BUSINESS_PARTNER": "HR Agent Only",
        "OPERATIONS_ANALYST": "Operations Agent Only",
        "CUSTOMER_SUCCESS_MANAGER": "Customer Service Agent Only",
    }
    specific = scope_map.get(role_scope)
    if specific:
        base.append(specific)
    # Also expose Marketing Agent Only if it ever gets added
    return base
