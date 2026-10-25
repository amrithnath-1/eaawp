"""
Knowledge indexing under the Gemini embedding quota: pacing, 429 retries, clear
failure messages, and the upload/background-task commit race.
"""
from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import settings
from app.services import vector_store as vs
from tests.conftest import _run
from tests.test_knowledge_access import KB, _vec, kb, upload  # noqa: F401  (kb is a fixture)

RATE_LIMIT = ("429 You exceeded your current quota, please check your plan and billing details. "
              "Quota exceeded for metric: generativelanguage.googleapis.com/embed_content_free_tier_requests, "
              "limit: 100, model: gemini-embedding-2. Please retry in 2.5s.")
DAILY_LIMIT = "429 RESOURCE_EXHAUSTED: Embed content requests per day limit exceeded on Free Tier."


@pytest.fixture()
def clock(monkeypatch):
    """Fake monotonic clock; sleeping advances it instantly and is recorded."""
    state = {"t": 1000.0, "sleeps": []}

    async def fake_sleep(seconds):
        state["sleeps"].append(seconds)
        state["t"] += seconds

    monkeypatch.setattr(vs, "_now", lambda: state["t"])
    monkeypatch.setattr(vs, "_sleep", fake_sleep)
    monkeypatch.setattr(vs, "_recent_embeds", vs.deque())
    return state


def test_large_document_is_paced_under_the_per_minute_budget(clock, monkeypatch):
    monkeypatch.setattr(settings, "gemini_embedding_rpm", 90)
    calls = []

    async def fake_embed(texts):
        calls.append((clock["t"], len(texts)))
        return [[0.0] for _ in texts]

    monkeypatch.setattr(vs, "embed_texts_gemini", fake_embed)
    out = _run(vs.embed_texts_for_indexing([f"chunk {i}" for i in range(233)]))

    assert len(out) == 233
    assert max(n for _, n in calls) <= 50
    for t, _ in calls:  # no rolling 60-second window ever exceeds the budget
        assert sum(n for s, n in calls if t - 60 < s <= t) <= 90
    assert clock["sleeps"], "a 233-chunk document must wait for quota rather than burst"


def test_rate_limited_batch_is_retried_after_the_suggested_delay(clock, monkeypatch):
    attempts = {"n": 0}

    async def flaky(texts):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError(RATE_LIMIT)
        return [[1.0] for _ in texts]

    monkeypatch.setattr(vs, "embed_texts_gemini", flaky)
    out = _run(vs.embed_texts_for_indexing(["a", "b", "c"]))
    assert len(out) == 3 and attempts["n"] == 2
    assert 2.5 in clock["sleeps"]


def test_daily_quota_fails_fast_with_a_clear_message(clock, monkeypatch):
    async def exhausted(texts):
        raise RuntimeError(DAILY_LIMIT)

    monkeypatch.setattr(vs, "embed_texts_gemini", exhausted)
    with pytest.raises(vs.EmbeddingQuotaError, match="daily embedding quota"):
        _run(vs.embed_texts_for_indexing(["a"]))
    assert clock["sleeps"] == []


def test_other_errors_are_not_retried(clock, monkeypatch):
    async def broken(texts):
        raise RuntimeError("400 API key not valid")

    monkeypatch.setattr(vs, "embed_texts_gemini", broken)
    with pytest.raises(RuntimeError, match="API key not valid"):
        _run(vs.embed_texts_for_indexing(["a"]))
    assert clock["sleeps"] == []


def test_persistent_rate_limit_marks_document_failed_with_readable_reason(kb, clock, monkeypatch):
    monkeypatch.setattr(settings, "gemini_embedding_max_retries", 2)

    async def always_limited(texts):
        raise RuntimeError(RATE_LIMIT)

    monkeypatch.setattr(vs, "embed_texts_gemini", always_limited)
    did = upload(kb, "a_admin", "quota.txt", b"pricing and refund policy for services")
    doc = {d["id"]: d for d in kb.client.get(f"{KB}/documents", headers=kb.auth("a_admin")).json()}[did]
    assert doc["status"] == "failed"
    assert "rate-limiting embedding requests after 2 retries" in doc["error_message"]


def test_paced_indexing_still_indexes_and_retrieves(kb, clock, monkeypatch):
    attempts = {"n": 0}

    async def first_call_limited(texts):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError(RATE_LIMIT)
        return [_vec(t) for t in texts]

    monkeypatch.setattr(vs, "embed_texts_gemini", first_call_limited)
    did = upload(kb, "a_admin", "hours.txt", b"office opening hours are nine to five on weekdays")
    doc = {d["id"]: d for d in kb.client.get(f"{KB}/documents", headers=kb.auth("a_admin")).json()}[did]
    assert doc["status"] == "indexed" and doc["error_message"] is None


def test_document_row_is_committed_before_background_processing_starts(kb, monkeypatch):
    """The background task opens its own session; the new row must already be visible to it."""
    seen: list[bool] = []

    def check_visible(doc_id, tenant_id):
        async def look():
            from app.db.models import KnowledgeDocument
            async with kb.maker() as s:
                return await s.get(KnowledgeDocument, doc_id) is not None
        with ThreadPoolExecutor(1) as ex:   # separate connection, as the real task uses
            seen.append(ex.submit(_run, look()).result())
        return asyncio.sleep(0)

    monkeypatch.setattr("app.api.routers.knowledge._process_in_background", check_visible)
    r = kb.client.post(f"{KB}/upload", headers=kb.auth("a_admin"), files={"file": ("r.txt", io.BytesIO(b"race check"))})
    assert r.status_code == 202, r.text
    assert seen == [True]
