"""
Knowledge retrieval keeps parsed embeddings in a per-process cache. The cache must never return another company's or
another access level's chunks, and must notice every change to the set of chunks it was built from.

FAKED: the query embedding (deterministic vectors), so similarity is predictable.
"""
from __future__ import annotations

import json
import uuid

import numpy as np
import pytest
from sqlalchemy import delete, select

from app.db.models import DocumentChunk, KnowledgeDocument
from app.services import vector_store as vs
from tests.conftest import _run

DIM = 8


def unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


@pytest.fixture()
def embed(monkeypatch):
    state = {"q": unit(0)}

    async def fake(_q):
        return state["q"]
    monkeypatch.setattr(vs, "embed_query_gemini", fake)
    vs._INDEX_CACHE.clear()
    return state


def add_doc(world, tenant, name, vec_index, level="All staff", scope="Global / Shared"):
    async def go():
        async with world.maker() as s:
            did = str(uuid.uuid4())
            s.add(KnowledgeDocument(id=did, tenant_id=tenant, name=name, doc_type="txt", status="indexed",
                                    access_level=level, role_scope=scope, storage_path="x", uploaded_by="t"))
            s.add(DocumentChunk(id=str(uuid.uuid4()), tenant_id=tenant, document_id=did, chunk_index=0,
                                text=f"text of {name}", embedding_json=json.dumps(unit(vec_index)), role_scope=scope))
            await s.commit()
            return did
    return _run(go())


def top(world, tenant, levels=("All staff",), role="DIGITAL_MARKETING_MANAGER", k=1):
    async def go():
        async with world.maker() as s:
            return [c.document_name for c in await vs.retrieve_similar_chunks(
                "q", tenant, role, s, top_k=k, access_levels=list(levels))]
    return _run(go())


def test_results_match_cosine_similarity_and_repeat_from_cache(world, embed):
    add_doc(world, world.tenant_a, "match", 0)
    add_doc(world, world.tenant_a, "other", 1)
    assert top(world, world.tenant_a, k=2) == ["match", "other"]
    assert len(vs._INDEX_CACHE) == 1
    assert top(world, world.tenant_a, k=2) == ["match", "other"]       # served from the cache


def test_cache_never_crosses_companies(world, embed):
    add_doc(world, world.tenant_a, "a-secret", 0)
    add_doc(world, world.tenant_b, "b-doc", 1)
    assert top(world, world.tenant_a, k=5) == ["a-secret"]
    assert top(world, world.tenant_b, k=5) == ["b-doc"]
    assert top(world, world.tenant_a, k=5) == ["a-secret"]


def test_cache_never_crosses_access_levels(world, embed):
    add_doc(world, world.tenant_a, "public", 1)
    add_doc(world, world.tenant_a, "admins-only", 0, level="Admins")
    assert top(world, world.tenant_a, levels=("All staff", "Managers", "Admins"))[0] == "admins-only"
    assert top(world, world.tenant_a, levels=("All staff",), k=5) == ["public"]


def test_a_new_document_is_seen_immediately(world, embed):
    add_doc(world, world.tenant_a, "old", 1)
    assert top(world, world.tenant_a) == ["old"]
    add_doc(world, world.tenant_a, "new-better", 0)
    assert top(world, world.tenant_a) == ["new-better"]


def test_a_deleted_document_disappears_immediately(world, embed):
    keep = add_doc(world, world.tenant_a, "keep", 1)
    gone = add_doc(world, world.tenant_a, "gone", 0)
    assert top(world, world.tenant_a) == ["gone"]

    async def drop():
        async with world.maker() as s:
            await s.execute(delete(DocumentChunk).where(DocumentChunk.document_id == gone))
            await s.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == gone))
            await s.commit()
    _run(drop())
    assert top(world, world.tenant_a, k=5) == ["keep"] and keep


def test_restricting_a_document_takes_effect_immediately(world, embed):
    add_doc(world, world.tenant_a, "general", 1)
    did = add_doc(world, world.tenant_a, "becomes-restricted", 0)
    assert top(world, world.tenant_a) == ["becomes-restricted"]

    async def restrict():
        async with world.maker() as s:
            row = (await s.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == did))).scalar_one()
            row.access_level = "Admins"
            await s.commit()
    _run(restrict())
    assert top(world, world.tenant_a, k=5) == ["general"]


def test_role_scoped_document_reaches_only_its_role(world, embed):
    add_doc(world, world.tenant_a, "clinic-only", 0, scope="Clinic Agent Only")
    add_doc(world, world.tenant_a, "shared", 1)
    assert top(world, world.tenant_a, role="MEDICAL_ASSISTANT") == ["clinic-only"]
    assert top(world, world.tenant_a, role="DIGITAL_MARKETING_MANAGER", k=5) == ["shared"]


def test_cache_is_bounded(world, embed):
    add_doc(world, world.tenant_a, "d", 0)
    for i in range(vs._INDEX_CACHE_MAX + 5):
        top(world, world.tenant_a, levels=("All staff", f"level-{i}"))
    assert len(vs._INDEX_CACHE) <= vs._INDEX_CACHE_MAX
    assert np.isclose(np.linalg.norm(next(iter(vs._INDEX_CACHE.values()))[1][0]), 1.0)
