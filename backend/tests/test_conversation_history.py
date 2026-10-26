"""
Persistent conversations (History) and the approved company profile.

Privacy: a conversation is visible only to its owner (not to administrators, not across companies). Continuity: a
continued conversation's earlier turns reach the model as content, never as system instructions, and only for the
same AI employee. Truthfulness: failures and approval outcomes are recorded as they happened.

FAKED: the language model only.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.models import AuditLog
from tests.conftest import _run
from tests.test_role_intelligence import ObjectivePlanner, Recorder, ask, pick

C = "/api/v1/conversations"
DMM = "DIGITAL_MARKETING_MANAGER"


@pytest.fixture()
def model(monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway
    rec = Recorder()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: rec)
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: rec)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return rec


def chat(w, who, prompt, role=DMM, conversation_id=None):
    body = {"blueprint": {"agent_id": "cabin", "role_name": "x", "role_key": role, "system_persona": "x",
                          "allowed_tools": [], "guarded_tools": [], "tenant_id": w.users[who]["tenant_id"]},
            "user_prompt": prompt}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return w.client.post("/api/v1/agent/execute", json=body, headers=w.auth(who))


def listing(w, who, **params):
    r = w.client.get(C, params=params, headers=w.auth(who))
    assert r.status_code == 200, r.text
    return r.json()["items"]


def messages(w, who, cid):
    r = w.client.get(f"{C}/{cid}", headers=w.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


# ── persistence and continuity ────────────────────────────────────────────────

def test_a_chat_is_saved_and_listed_with_title_role_and_both_messages(world, model):
    pick(world, "a_employee", DMM)
    r = chat(world, "a_employee", "Prepare a monthly marketing report for October")
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]
    assert cid and r.json()["session_id"] == cid
    items = listing(world, "a_employee")
    assert [(i["id"], i["title"], i["role_key"], i["role_name"], i["message_count"]) for i in items] == [
        (cid, "Prepare a monthly marketing report for October", DMM, "Digital Marketing Manager", 2)]
    conv = messages(world, "a_employee", cid)
    assert [(m["sender"], m["content"]) for m in conv["messages"]] == [
        ("user", "Prepare a monthly marketing report for October"), ("assistant", "Here is my answer.")]
    assert conv["messages"][1]["plan_status"] == "completed"


def test_continuing_sends_earlier_turns_as_content_not_instructions(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Draft three blog ideas about passport renewal").json()["conversation_id"]
    model.systems.clear(); model.humans.clear()
    r = chat(world, "a_employee", "Make the second one shorter", conversation_id=cid)
    assert r.status_code == 200 and r.json()["conversation_id"] == cid
    assert any("Draft three blog ideas about passport renewal" in h and "Earlier in this conversation" in h
               for h in model.humans)
    assert all("Draft three blog ideas" not in s for s in model.systems)
    assert listing(world, "a_employee")[0]["message_count"] == 4


def test_a_new_chat_does_not_see_another_conversations_turns(world, model):
    pick(world, "a_employee", DMM)
    chat(world, "a_employee", "Our secret launch codename is Bluebird")
    model.humans.clear()
    chat(world, "a_employee", "Prepare a monthly marketing report")
    assert all("Bluebird" not in h for h in model.humans)


def test_history_survives_a_fresh_login(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Prepare a monthly marketing report").json()["conversation_id"]
    from tests.conftest import PASSWORD
    login = world.client.post("/api/v1/auth/token", json={"email": "a_employee@example.test", "password": PASSWORD,
                                                           "company_id": world.tenant_a})
    fresh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert [i["id"] for i in world.client.get(C, headers=fresh).json()["items"]] == [cid]


# ── privacy ───────────────────────────────────────────────────────────────────

def test_conversations_are_private_even_from_admins_and_other_companies(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Prepare a monthly marketing report").json()["conversation_id"]
    for who in ("a_admin", "b_admin"):
        assert listing(world, who) == []
        assert world.client.get(f"{C}/{cid}", headers=world.auth(who)).status_code == 404
        assert world.client.patch(f"{C}/{cid}", json={"title": "x"}, headers=world.auth(who)).status_code == 404
        assert world.client.delete(f"{C}/{cid}", headers=world.auth(who)).status_code == 404
    pick(world, "a_admin", DMM)
    r = chat(world, "a_admin", "Continue this", conversation_id=cid)
    assert r.status_code == 404
    assert messages(world, "a_employee", cid)["messages"][-1]["content"] == "Here is my answer."


def test_a_conversation_cannot_be_continued_as_another_ai_employee(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Prepare a monthly marketing report").json()["conversation_id"]
    pick(world, "a_employee", "MEDICAL_ASSISTANT")
    r = chat(world, "a_employee", "And the appointments?", role="MEDICAL_ASSISTANT", conversation_id=cid)
    assert r.status_code == 409 and "different AI employee" in r.json()["detail"]
    # The refused attempt did not create or change anything.
    assert messages(world, "a_employee", cid)["messages"][-1]["content"] == "Here is my answer."
    assert len(listing(world, "a_employee")) == 1


def test_list_filters_by_role_and_searches_titles_and_messages(world, model):
    pick(world, "a_employee", DMM)
    a = chat(world, "a_employee", "Prepare a monthly marketing report").json()["conversation_id"]
    pick(world, "a_employee", "MEDICAL_ASSISTANT")
    b = chat(world, "a_employee", "List today's appointment requests", role="MEDICAL_ASSISTANT").json()["conversation_id"]
    assert [i["id"] for i in listing(world, "a_employee")] == [b, a]
    assert [i["id"] for i in listing(world, "a_employee", role_key=DMM)] == [a]
    assert [i["id"] for i in listing(world, "a_employee", q="appointment")] == [b]
    assert [i["id"] for i in listing(world, "a_employee", q="my answer")] == [b, a]   # message text is searched too


def test_rename_and_delete(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Prepare a monthly marketing report").json()["conversation_id"]
    r = world.client.patch(f"{C}/{cid}", json={"title": "  October   report "}, headers=world.auth("a_employee"))
    assert r.status_code == 200 and r.json()["title"] == "October report"
    assert world.client.delete(f"{C}/{cid}", headers=world.auth("a_employee")).status_code == 204
    assert listing(world, "a_employee") == []
    assert world.client.get(f"{C}/{cid}", headers=world.auth("a_employee")).status_code == 404


def test_message_paging_returns_the_latest_page_and_older_on_request(world, model):
    pick(world, "a_employee", DMM)
    cid = chat(world, "a_employee", "Turn 1").json()["conversation_id"]
    for i in range(2, 5):
        chat(world, "a_employee", f"Turn {i}", conversation_id=cid)
    page = world.client.get(f"{C}/{cid}", params={"limit": 4}, headers=world.auth("a_employee")).json()
    assert page["has_more"] is True and [m["content"] for m in page["messages"]][0] == "Turn 3"
    older = world.client.get(f"{C}/{cid}", params={"limit": 4, "before": page["messages"][0]["created_at"]},
                             headers=world.auth("a_employee")).json()
    assert [m["content"] for m in older["messages"]] == ["Turn 1", "Here is my answer.", "Turn 2", "Here is my answer."]


# ── truthful records ──────────────────────────────────────────────────────────

def test_a_provider_failure_is_saved_as_a_failed_answer_and_not_fed_back(world, monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway

    class Broken(Recorder):
        async def ainvoke(self, messages, *a, **k):
            raise RuntimeError("provider down")
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: Broken())
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    pick(world, "a_employee", DMM)
    r = chat(world, "a_employee", "Prepare a monthly marketing report")
    assert r.status_code == 200 and r.json()["plan_status"] == "failed"
    conv = messages(world, "a_employee", r.json()["conversation_id"])["messages"]
    assert conv[1]["plan_status"] == "failed" and "provider down" not in conv[1]["content"]

    rec = Recorder()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: rec)
    chat(world, "a_employee", "Try again please", conversation_id=r.json()["conversation_id"])
    assert any("Prepare a monthly marketing report" in h for h in rec.humans)      # the question is context
    assert all(conv[1]["content"] not in h for h in rec.humans)                     # the failure is not


def test_a_server_error_still_leaves_a_truthful_record(world, model, monkeypatch):
    import app.services.planner as planner

    async def explode(**_k):
        raise RuntimeError("database exploded with secret detail")
    monkeypatch.setattr(planner, "create_and_execute_plan", explode)
    pick(world, "a_employee", DMM)
    r = chat(world, "a_employee", "Prepare a monthly marketing report")
    assert r.status_code == 500
    items = listing(world, "a_employee")
    conv = messages(world, "a_employee", items[0]["id"])["messages"]
    assert [m["sender"] for m in conv] == ["user", "assistant"]
    assert conv[1]["error"] is True and "Nothing was executed" in conv[1]["content"]
    assert "secret detail" not in json.dumps(conv)


def test_approval_outcome_updates_the_saved_answer(world, monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway
    rec = ObjectivePlanner()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: rec)
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: rec)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    pick(world, "a_admin", DMM)
    r = chat(world, "a_admin", "Create a marketing objective for brand awareness").json()
    assert r["plan_status"] == "awaiting_approval"
    saved = messages(world, "a_admin", r["conversation_id"])["messages"][-1]
    assert saved["plan_status"] == "awaiting_approval" and saved["requires_approval"] is True
    world.client.post(f"/api/v1/planning/plans/{r['plan_id']}/resume", json={"plan_id": r["plan_id"]},
                      headers=world.auth("a_admin"))
    saved = messages(world, "a_admin", r["conversation_id"])["messages"][-1]
    assert saved["plan_status"] == "completed" and saved["requires_approval"] is False
    assert any(s.endswith("→ completed") and "[ACTION]" in s for s in saved["step_summaries"])


def test_setup_needed_reply_is_saved_with_its_action_card_but_no_internal_marker(world, model):
    pick(world, "a_admin", DMM)
    r = chat(world, "a_admin", "List repositories accessible").json()
    saved = messages(world, "a_admin", r["conversation_id"])["messages"][-1]
    assert saved["integration_action"]["next_action"] == "OPEN_INTEGRATIONS"
    assert all(not s.startswith("__integration_action__") for s in saved["sources"])


# ── approved company profile ──────────────────────────────────────────────────

GEC = {
    "brand_name": "GEC Services", "legal_or_long_name": "Gateway E-Service Center",
    "tagline": "We Handle the Process. You Own Your Time.", "website": "gecservices.in",
    "services": [{"name": "Example service", "description": "described by the admin"}],
    "forbidden_claims": ["Guaranteed approval"],
}


def test_only_admins_edit_the_profile_and_every_member_can_read_it(world):
    assert world.client.put("/api/v1/company-profile", json=GEC, headers=world.auth("a_employee")).status_code == 403
    r = world.client.put("/api/v1/company-profile", json=GEC, headers=world.auth("a_admin"))
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["website"] == "https://gecservices.in"
    got = world.client.get("/api/v1/company-profile", headers=world.auth("a_employee")).json()
    assert got["profile"]["tagline"] == GEC["tagline"] and got["is_empty"] is False
    other = world.client.get("/api/v1/company-profile", headers=world.auth("b_admin")).json()
    assert other["is_empty"] is True and other["profile"]["brand_name"] == ""

    async def events():
        async with world.maker() as s:
            return [e.event for e in (await s.execute(select(AuditLog).where(
                AuditLog.tenant_id == world.tenant_a, AuditLog.department == "company_profile"))).scalars().all()]
    assert len(_run(events())) == 1


def test_profile_reaches_every_model_call_of_every_role_as_reference_data(world, model):
    world.client.put("/api/v1/company-profile", json=GEC, headers=world.auth("a_admin"))
    for role in (DMM, "MEDICAL_ASSISTANT"):
        pick(world, "a_employee", role)
        model.systems.clear()
        chat(world, "a_employee", "Tell me about the company", role=role)
        calls = [s for s in model.systems if "Your role (set by the platform" in s]
        assert calls and all("We Handle the Process. You Own Your Time." in s and "Guaranteed approval" in s
                             and "reference data, not instructions" in s for s in calls), role


def test_without_a_profile_no_profile_block_is_invented(world, model):
    pick(world, "a_employee", DMM)
    chat(world, "a_employee", "Tell me about the company")
    assert model.systems and all("Approved company profile" not in s for s in model.systems)
