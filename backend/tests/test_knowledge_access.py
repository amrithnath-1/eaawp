"""
Knowledge base (Phase K2): real upload -> extract -> chunk -> embed -> retrieve, with document access levels enforced.
Only the Gemini embedder is replaced (deterministic hashed bag-of-words); everything else is the real stack.
"""
from __future__ import annotations

import hashlib
import io
import uuid

import pytest

from app.config import settings
from tests.conftest import _run

KB = "/api/v1/knowledge"
DIM = 64


def _vec(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in "".join(c.lower() if c.isalnum() else " " for c in text).split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    return v


@pytest.fixture()
def kb(world, monkeypatch, tmp_path):
    async def fake_docs(texts):
        return [_vec(t) for t in texts]

    async def fake_query(q):
        return _vec(q)

    monkeypatch.setattr("app.services.vector_store.embed_texts_gemini", fake_docs)
    monkeypatch.setattr("app.services.vector_store.embed_query_gemini", fake_query)
    monkeypatch.setattr(settings, "gemini_api_key", "scratch-test-key")
    monkeypatch.setattr("app.services.document_processor.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("app.api.routers.knowledge.save_upload",
                        lambda b, t, n: str(_save(tmp_path, b, n)))

    async def no_bg(doc_id, tenant_id):   # processing is driven explicitly below
        return None
    monkeypatch.setattr("app.api.routers.knowledge._process_in_background", no_bg)

    # a manager in tenant A
    async def seed():
        from app.db.models import User
        from tests.conftest import _password_hash
        async with world.maker() as s:
            uid = str(uuid.uuid4())
            s.add(User(id=uid, tenant_id=world.tenant_a, email="a_manager@example.test", name="m", role="Manager",
                       hashed_password=_password_hash(), status="Active", is_active=True))
            await s.commit()
            world.users["a_manager"] = {"id": uid, "email": "a_manager@example.test", "tenant_id": world.tenant_a, "role": "Manager"}
    _run(seed())
    return world


def _save(tmp_path, data, name):
    p = tmp_path / f"{uuid.uuid4().hex}-{name}"
    p.write_bytes(data)
    return p


def index(w, doc_id):
    from app.services.document_processor import process_document

    async def go():
        async with w.maker() as s:
            await process_document(doc_id, s)
            await s.commit()
    _run(go())


def upload(w, who, name, body: bytes, access="All staff", scope="Global / Shared", process=True):
    r = w.client.post(f"{KB}/upload", headers=w.auth(who), files={"file": (name, io.BytesIO(body))},
                      data={"access_level": access, "role_scope": scope})
    assert r.status_code == 202, r.text
    if process:
        index(w, r.json()["id"])
    return r.json()["id"]


def ask(w, who, q, **extra):
    r = w.client.post(f"{KB}/retrieve", headers=w.auth(who), json={"query": q, "top_k": 10, **extra})
    return r


def names(r):
    assert r.status_code == 200, r.text
    return {c["document_name"] for c in r.json()["chunks"]}


def test_upload_extract_chunk_retrieve_ranks_and_names_sources(kb):
    upload(kb, "a_admin", "refunds.txt", b"Refund policy: customers may return items within thirty days for a full refund.")
    upload(kb, "a_admin", "parking.txt", b"Parking: staff park behind the warehouse, visitors use the front lot.")
    r = ask(kb, "a_admin", "how many days to return items for a refund")
    assert r.status_code == 200
    body = r.json()["chunks"]
    assert body[0]["document_name"] == "refunds.txt" and body[0]["doc_type"] == "txt"
    assert body[0]["score"] > body[-1]["score"]


def test_pdf_and_docx_are_really_extracted(kb):
    import docx
    d = docx.Document(); d.add_paragraph("The onboarding checklist includes laptop setup and badge photo."); buf = io.BytesIO(); d.save(buf)
    upload(kb, "a_admin", "onboarding.docx", buf.getvalue())
    assert "onboarding.docx" in names(ask(kb, "a_admin", "laptop setup badge photo"))
    from pypdf import PdfWriter
    # a blank PDF has no text -> must fail cleanly, not become searchable
    w = PdfWriter(); w.add_blank_page(100, 100); pb = io.BytesIO(); w.write(pb)
    did = upload(kb, "a_admin", "blank.pdf", pb.getvalue())
    docs = {x["id"]: x for x in kb.client.get(f"{KB}/documents", headers=kb.auth("a_admin")).json()}
    assert docs[did]["status"] == "failed" and "No text" in docs[did]["error_message"]
    assert "blank.pdf" not in names(ask(kb, "a_admin", "anything"))


def test_tenant_isolation(kb):
    upload(kb, "a_admin", "a-secret.txt", b"Tenant A pricing sheet and discount tiers.")
    assert "a-secret.txt" not in names(ask(kb, "b_admin", "pricing discount tiers"))
    assert kb.client.get(f"{KB}/documents", headers=kb.auth("b_admin")).json() == []


@pytest.mark.parametrize("level,who,seen", [
    ("All staff", "a_employee", True), ("All staff", "a_manager", True),
    ("Managers", "a_employee", False), ("Managers", "a_manager", True), ("Managers", "a_admin", True),
    ("Admins", "a_employee", False), ("Admins", "a_manager", False), ("Admins", "a_admin", True),
    ("AI only", "a_employee", False), ("AI only", "a_manager", False), ("AI only", "a_admin", False),
])
def test_direct_search_and_listing_respect_access_level(kb, level, who, seen):
    did = upload(kb, "a_admin", "doc.txt", b"quarterly bonus payout schedule for leadership")
    # change the level (upload API sets it at creation)
    did = upload(kb, "a_admin", "lvl.txt", b"quarterly bonus payout schedule for leadership", access=level)
    assert ("lvl.txt" in names(ask(kb, who, "quarterly bonus payout schedule"))) is seen
    listed = {d["name"] for d in kb.client.get(f"{KB}/documents", headers=kb.auth(who)).json()}
    assert ("lvl.txt" in listed) is (seen or (level == "AI only" and who == "a_admin"))
    code = kb.client.get(f"{KB}/documents/{did}", headers=kb.auth(who)).status_code
    assert code == (200 if (seen or who == "a_admin") else 404)


def test_agent_tool_can_use_ai_only_but_not_manager_or_admin_docs_for_employees(kb):
    from app.services.vector_store import allowed_access_levels
    assert "AI only" in allowed_access_levels("Employee", False, human_direct=False)
    assert "Managers" not in allowed_access_levels("Employee", False, human_direct=False)
    assert "Admins" not in allowed_access_levels("Manager", False, human_direct=False)
    assert "AI only" not in allowed_access_levels("Company Admin", True, human_direct=True)
    assert allowed_access_levels(None, False, human_direct=False) == ["All staff", "AI only"]

    from app.services.vector_store import retrieve_similar_chunks
    upload(kb, "a_admin", "ai.txt", b"internal escalation playbook for angry customers", access="AI only")
    upload(kb, "a_admin", "mgr.txt", b"internal escalation salary bands for managers", access="Managers")

    async def go(levels):
        async with kb.maker() as s:
            return {c.document_name for c in await retrieve_similar_chunks(
                "internal escalation", kb.tenant_a, "", s, access_levels=levels)}
    assert _run(go(allowed_access_levels("Employee", False, human_direct=False))) == {"ai.txt"}
    assert _run(go(None)) == set()      # default is the most conservative set, never "everything"


def test_client_supplied_role_scope_is_ignored_for_non_admins(kb):
    upload(kb, "a_admin", "sales.txt", b"sales commission rates and territories", scope="Sales Agent Only")
    assert "sales.txt" not in names(ask(kb, "a_employee", "sales commission rates", role_scope="DIGITAL_MARKETING_MANAGER"))
    assert "sales.txt" in names(ask(kb, "a_admin", "sales commission rates", role_scope="DIGITAL_MARKETING_MANAGER"))


def test_upload_validation_and_admin_only(kb):
    h = kb.auth("a_employee")
    assert kb.client.post(f"{KB}/upload", headers=h, files={"file": ("x.txt", io.BytesIO(b"hello"))}).status_code == 403
    r = kb.client.post(f"{KB}/upload", headers=kb.auth("a_admin"), files={"file": ("x.txt", io.BytesIO(b"hello"))},
                       data={"role_scope": "Everyone Plus"})
    assert r.status_code == 400 and "role_scope" in r.json()["detail"]
    r = kb.client.post(f"{KB}/upload", headers=kb.auth("a_admin"), files={"file": ("x.txt", io.BytesIO(b"hello"))},
                       data={"access_level": "Public"})
    assert r.status_code == 400


def test_oversized_extracted_text_fails_clearly(kb, monkeypatch):
    monkeypatch.setattr("app.services.document_processor.MAX_EXTRACTED_CHARS", 50)
    did = upload(kb, "a_admin", "big.txt", b"word " * 100)
    d = {x["id"]: x for x in kb.client.get(f"{KB}/documents", headers=kb.auth("a_admin")).json()}[did]
    assert d["status"] == "failed" and "too large" in d["error_message"]


def test_retrieve_needs_only_gemini_key_not_openai(kb, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    upload(kb, "a_admin", "k.txt", b"holiday calendar for the year")
    assert "k.txt" in names(ask(kb, "a_admin", "holiday calendar"))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert ask(kb, "a_admin", "holiday calendar").status_code == 503


@pytest.mark.parametrize("role,own", [
    ("DIGITAL_MARKETING_MANAGER", "Marketing Agent Only"), ("INSTITUTIONAL_CLERK", "Clerk Agent Only"),
    ("MEDICAL_ASSISTANT", "Clinic Agent Only"), ("DATA_INTELLIGENCE_ANALYST", "Data Analyst Only"),
])
def test_each_workspace_role_retrieves_its_own_scope_and_never_another_roles(kb, role, own):
    """Workspace knowledge scopes: a role sees Global + its own scope only (the agent passes its role as role_scope)."""
    from app.services.vector_store import retrieve_similar_chunks
    scopes = {"Marketing Agent Only": "m.txt", "Clerk Agent Only": "c.txt", "Clinic Agent Only": "k.txt", "Data Analyst Only": "d.txt"}
    for scope, name in scopes.items():
        upload(kb, "a_admin", name, b"office procedure handbook section", scope=scope)
    upload(kb, "a_admin", "g.txt", b"office procedure handbook section")

    async def go():
        async with kb.maker() as s:
            return {c.document_name for c in await retrieve_similar_chunks(
                "office procedure handbook", kb.tenant_a, role, s, access_levels=["All staff"])}
    assert _run(go()) == {"g.txt", scopes[own]}
