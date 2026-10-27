"""
Medical Assistant (Phase I): a clinic-SUPPORT assistant with hard boundaries. REAL: guard, API, auth, tenancy, workflow, DB,
audit, tools, pipeline. FAKED: the LLM only. The safety screen is deterministic and is tested WITHOUT any model.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.models import AuditLog
from app.services import medical_guard as g
from tests.test_marketing_analytics_e2e import run

API = "/api/v1/clinic"


def future(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def book(world, who="a_employee", reason="I would like a check-up next week", **over):
    return world.client.post(f"{API}/appointments", json={"reason": reason, **over}, headers=world.auth(who))


def make(world, who="a_employee", **kw):
    r = book(world, who, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def set_status(world, aid, to, who="a_admin", **extra):
    return world.client.post(f"{API}/appointments/{aid}/status", json={"status": to, **extra}, headers=world.auth(who))


def audit_text(world):
    async def ev():
        async with world.maker() as s:
            return " | ".join(a.event for a in (await s.execute(select(AuditLog))).scalars().all())
    return run(ev())


# ── the deterministic safety screen (no LLM anywhere) ───────────────────────────────

class TestGuard:
    @pytest.mark.parametrize("text", [
        "I have crushing chest pain and my left arm is numb", "he is unconscious and not breathing", "I can't breathe properly",
        "her face is drooping and her speech is slurred speech", "the bleeding won't stop", "my child swallowed bleach",
        "I think I overdosed", "my throat is swelling after the injection", "He is having a seizure",
    ])
    def test_emergencies_are_caught(self, text):
        out = g.screen(text)
        assert out is not None and out.kind == "emergency" and "emergency number" in out.message

    @pytest.mark.parametrize("text", ["I want to kill myself", "i don't want to be alive anymore", "thinking about self-harm"])
    def test_crisis_wording_gets_a_supportive_message(self, text):
        out = g.screen(text)
        assert out.kind == "crisis" and "988" in out.message and "emergency number" in out.message

    @pytest.mark.parametrize("text", [
        "What dose of ibuprofen should I take?", "Can I take paracetamol with my blood pressure tablets?", "Do I have diabetes?",
        "Can you diagnose this rash", "Should I stop taking my antidepressant", "which antibiotic is best for a sore throat",
    ])
    def test_medical_advice_requests_hit_the_boundary(self, text):
        out = g.screen(text)
        assert out is not None and out.kind == "boundary" and "can't give medical advice" in out.message

    @pytest.mark.parametrize("text", [
        "What are your opening hours?", "I'd like to book an appointment for next Tuesday", "Where is the clinic located?",
        "Please remind me what to bring to my appointment", "How do I cancel my booking?",
    ])
    def test_ordinary_admin_questions_pass(self, text):
        assert g.screen(text) is None

    def test_emergency_wins_over_advice_and_crisis_wins_over_both(self):
        assert g.screen("chest pain, what dose of aspirin should I take?").kind == "emergency"
        assert g.screen("chest pain and I want to die").kind == "crisis"

    def test_flags_list_the_matching_phrases(self):
        assert "chest pain" in g.emergency_flags("Sudden Chest Pain since morning") and g.emergency_flags("routine check") == []


# ── booking & visibility ─────────────────────────────────────────────────────────

class TestBooking:
    def test_member_requests_an_appointment_with_a_disclaimer(self, world):
        a = make(world)
        assert a["status"] == "requested" and a["red_flag"] is False and a["emergency_notice"] is None and "does not give medical advice" in a["disclaimer"]

    def test_urgent_wording_flags_the_request_returns_a_notice_and_sorts_first(self, world):
        make(world, reason="Annual check-up please")
        urgent = make(world, reason="Chest pain since this morning")
        assert urgent["red_flag"] is True and "chest pain" in urgent["red_flags"] and "emergency number" in urgent["emergency_notice"]
        listed = world.client.get(f"{API}/appointments", headers=world.auth("a_admin")).json()
        assert listed[0]["id"] == urgent["id"]
        assert "URGENT" in audit_text(world)

    @pytest.mark.parametrize("over", [{"reason": "x"}, {"reason": "  "}])
    def test_reason_is_required(self, world, over):
        assert book(world, **over).status_code == 422

    def test_open_request_cap(self, world):
        for i in range(10):
            assert book(world, reason=f"Check-up number {i}").status_code == 201
        assert book(world, reason="one too many").status_code == 429

    def test_patients_only_see_their_own_staff_see_all(self, world):
        mine = make(world, who="a_employee"); other = make(world, who="a_admin")
        assert [x["id"] for x in world.client.get(f"{API}/appointments", headers=world.auth("a_employee")).json()] == [mine["id"]]
        assert {x["id"] for x in world.client.get(f"{API}/appointments", headers=world.auth("a_admin")).json()} == {mine["id"], other["id"]}
        assert world.client.get(f"{API}/appointments/{other['id']}", headers=world.auth("a_employee")).status_code == 404

    def test_other_company_gets_404(self, world):
        a = make(world)
        h = world.auth("b_admin")
        assert world.client.get(f"{API}/appointments", headers=h).json() == []
        for call in (lambda: world.client.get(f"{API}/appointments/{a['id']}", headers=h),
                     lambda: set_status(world, a["id"], "confirmed", who="b_admin", scheduled_for=future()),
                     lambda: world.client.post(f"{API}/appointments/{a['id']}/notes", json={"text": "hi"}, headers=h),
                     lambda: world.client.post(f"{API}/appointments/{a['id']}/summarize", headers=h),
                     lambda: world.client.delete(f"{API}/appointments/{a['id']}", headers=h)):
            assert call().status_code == 404

    def test_unauthenticated_is_rejected(self, world):
        assert world.client.get(f"{API}/appointments").status_code == 401

    def test_screen_endpoint_is_available_to_any_member(self, world):
        r = world.client.post(f"{API}/screen", json={"text": "I can't breathe"}, headers=world.auth("a_employee")).json()
        assert r["kind"] == "emergency"
        assert world.client.post(f"{API}/screen", json={"text": "opening hours?"}, headers=world.auth("a_employee")).json()["kind"] is None


# ── workflow ─────────────────────────────────────────────────────────────────────

class TestWorkflow:
    def test_staff_confirm_reschedule_complete(self, world):
        a = make(world)
        assert set_status(world, a["id"], "confirmed").status_code == 422                          # needs a time
        assert set_status(world, a["id"], "confirmed", scheduled_for="2020-01-01T10:00").status_code == 422   # in the past
        ok = set_status(world, a["id"], "confirmed", scheduled_for=future(3), clinician_name="Dr. Rao").json()
        assert ok["status"] == "confirmed" and ok["clinician_name"] == "Dr. Rao"
        resched = set_status(world, a["id"], "confirmed", scheduled_for=future(5)).json()
        assert resched["scheduled_for"] != ok["scheduled_for"]
        assert set_status(world, a["id"], "completed").json()["status"] == "completed"
        assert set_status(world, a["id"], "cancelled").status_code == 409

    def test_only_staff_change_status(self, world):
        a = make(world)
        assert set_status(world, a["id"], "confirmed", who="a_employee", scheduled_for=future()).status_code == 403

    def test_patient_cancels_only_their_own_open_request(self, world):
        a = make(world); other = make(world, who="a_admin")
        assert world.client.post(f"{API}/appointments/{other['id']}/cancel", headers=world.auth("a_employee")).status_code == 404
        assert world.client.post(f"{API}/appointments/{a['id']}/cancel", headers=world.auth("a_employee")).json()["status"] == "cancelled"
        assert world.client.post(f"{API}/appointments/{a['id']}/cancel", headers=world.auth("a_employee")).status_code == 409

    def test_staff_cannot_use_the_patient_cancel_endpoint(self, world):
        a = make(world)
        r = world.client.post(f"{API}/appointments/{a['id']}/cancel", headers=world.auth("a_admin"))
        assert r.status_code == 403

    def test_internal_notes_are_staff_only(self, world):
        a = make(world)
        assert world.client.post(f"{API}/appointments/{a['id']}/notes", json={"text": "x", "internal": True}, headers=world.auth("a_employee")).status_code == 403
        world.client.post(f"{API}/appointments/{a['id']}/notes", json={"text": "Patient called twice", "internal": True}, headers=world.auth("a_admin"))
        world.client.post(f"{API}/appointments/{a['id']}/notes", json={"text": "Please bring your insurance card"}, headers=world.auth("a_admin"))
        emp = json.dumps(world.client.get(f"{API}/appointments/{a['id']}", headers=world.auth("a_employee")).json())
        assert "insurance card" in emp and "called twice" not in emp

    def test_closed_appointment_takes_no_more_messages(self, world):
        a = make(world)
        world.client.post(f"{API}/appointments/{a['id']}/cancel", headers=world.auth("a_employee"))
        assert world.client.post(f"{API}/appointments/{a['id']}/notes", json={"text": "hello?"}, headers=world.auth("a_employee")).status_code == 409

    def test_staff_access_to_a_patients_record_is_audited_and_erasure_works(self, world):
        a = make(world)
        world.client.get(f"{API}/appointments/{a['id']}", headers=world.auth("a_admin"))
        assert "staff viewed appointment record" in audit_text(world)
        assert world.client.delete(f"{API}/appointments/{a['id']}", headers=world.auth("a_employee")).status_code == 403
        assert world.client.delete(f"{API}/appointments/{a['id']}", headers=world.auth("a_admin")).status_code == 204
        assert world.client.get(f"{API}/appointments/{a['id']}", headers=world.auth("a_admin")).status_code == 404
        assert "erased appointment record" in audit_text(world)


# ── intake summary ───────────────────────────────────────────────────────────────

class Model:
    def __init__(self, h):
        self.h = h

    def bind_tools(self, t):
        return self

    async def ainvoke(self, messages, *a, **k):
        if "restate a patient's own message" in str(messages[0].content):
            return AIMessage(content=json.dumps(self.h.summary) if not isinstance(self.h.summary, str) else self.h.summary)
        return AIMessage(content="{}")


@pytest.fixture()
def llm(monkeypatch):
    from app.llm.gateway import LLMGateway
    h = SimpleNamespace(summary={"symptoms_reported": ["sore knee", "trouble sleeping", "early stage arthritis"], "duration": "two weeks",
                                 "medications_mentioned": ["ibuprofen"], "allergies_mentioned": ["penicillin"]}, ready=True)
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: Model(h))
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: Model(h))
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=h.ready))
    return h


class TestIntakeSummary:
    REASON = "My sore knee has hurt for two weeks and I have trouble sleeping. I take ibuprofen and I am allergic to penicillin."

    def test_only_the_patients_own_words_survive(self, world, llm):
        a = make(world, reason=self.REASON)
        r = world.client.post(f"{API}/appointments/{a['id']}/summarize", headers=world.auth("a_admin")).json()
        assert r["intake"]["symptoms_reported"] == ["sore knee", "trouble sleeping"]          # the invented diagnosis is dropped
        assert r["intake"]["duration"] == "two weeks" and r["intake"]["medications_mentioned"] == ["ibuprofen"]
        assert "Not a diagnosis" in r["intake"]["note"]
        assert "arthritis" not in json.dumps(r["intake"])

    def test_staff_only_and_error_paths(self, world, llm):
        a = make(world, reason=self.REASON)
        assert world.client.post(f"{API}/appointments/{a['id']}/summarize", headers=world.auth("a_employee")).status_code == 403
        llm.summary = "nonsense"
        assert world.client.post(f"{API}/appointments/{a['id']}/summarize", headers=world.auth("a_admin")).status_code == 422
        llm.ready = False
        assert world.client.post(f"{API}/appointments/{a['id']}/summarize", headers=world.auth("a_admin")).status_code == 503


# ── agent side ───────────────────────────────────────────────────────────────────

class PipelineModel:
    """If the guard fails to stop a message, this model would answer with advice - the tests assert it is never reached."""
    calls = 0

    def bind_tools(self, t):
        return self

    async def ainvoke(self, messages, *a, **k):
        PipelineModel.calls += 1
        system, human = str(messages[0].content), str(messages[-1].content)
        if "planning assistant" in system:
            return AIMessage(content=json.dumps({"objective": "List", "steps": [
                {"step_index": 0, "step_type": "read", "description": "List appointments", "tool_name": "list_appointments",
                 "arguments": {"params": "{}"}, "depends_on": []},
                {"step_index": 1, "step_type": "response", "description": "Report", "tool_name": None, "arguments": {}, "depends_on": [0]}]}))
        if "Information gathered" in human:
            return AIMessage(content="Appointments:\n" + human.split("Information gathered:\n", 1)[1].split("\n\nUsing the information", 1)[0])
        return AIMessage(content="You should take 400mg of ibuprofen.")        # medical advice: must never reach the user


@pytest.fixture()
def pipeline(monkeypatch):
    from app.llm.gateway import LLMGateway
    PipelineModel.calls = 0
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: PipelineModel())
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: PipelineModel())
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))


def ask(world, who, prompt):
    body = {"blueprint": {"agent_id": "m1", "role_name": "Medical Assistant", "role_key": "MEDICAL_ASSISTANT", "system_persona": "p",
                          "allowed_tools": [], "guarded_tools": [], "tenant_id": world.users[who]["tenant_id"]}, "user_prompt": prompt}
    return world.client.post("/api/v1/agent/execute", json=body, headers=world.auth(who))


class TestAgent:
    def test_role_is_available_with_safe_defaults(self, world):
        r = world.client.get("/api/v1/roles/MEDICAL_ASSISTANT", headers=world.auth("a_admin"))
        assert r.status_code == 200, r.text
        scopes = {t["tool_key"]: t["governance"] for t in r.json()["tool_scopes"]}
        assert scopes["update_appointment_status"] == "requires_approval" and "send_email" not in scopes and "draft_email" not in scopes
        assert "NOT a clinician" in r.json()["instructions"]

    @pytest.mark.parametrize("prompt,fragment", [
        ("I have chest pain and cannot breathe", "emergency number"),
        ("I want to end my life", "crisis line"),
        ("What dose of ibuprofen should I take for my knee?", "can't give medical advice"),
    ])
    def test_the_guard_answers_before_any_model_is_called(self, world, pipeline, prompt, fragment):
        r = ask(world, "a_employee", prompt)
        assert r.status_code == 200, r.text
        assert fragment in r.json()["message"] and "400mg" not in r.text
        assert PipelineModel.calls == 0 and r.json()["tool_calls"] == [] and r.json()["plan_id"] is None

    def test_the_asker_decides_which_appointments_the_agent_can_see(self, world, pipeline):
        make(world, who="a_employee", reason="Routine check-up for my daughter")
        make(world, who="a_admin", reason="Private follow-up about my results")
        emp = ask(world, "a_employee", "Show my appointments")
        assert emp.status_code == 200 and "ID:" in emp.text and emp.text.count("ID:") == 1
        adm = ask(world, "a_admin", "Show appointments")
        assert adm.text.count("ID:") == 2
        assert "ID:" not in ask(world, "b_admin", "Show appointments").text

    def test_agent_conversations_about_health_are_never_stored_in_shared_memory(self, world, pipeline):
        """Memory is shared company-wide; for this role nothing may be stored. Read-only tools => the simple path,
        which is the one that stores memory for other roles."""
        from app.db.memory_models import AgentMemory
        from app.db.models import RoleConfiguration
        make(world, who="a_admin", reason="Private follow-up")
        assert world.client.get("/api/v1/roles/MEDICAL_ASSISTANT", headers=world.auth("a_admin")).status_code == 200

        async def read_only_tools():
            async with world.maker() as s:
                row = (await s.execute(select(RoleConfiguration).where(RoleConfiguration.tenant_id == world.tenant_a,
                                                                       RoleConfiguration.role_key == "MEDICAL_ASSISTANT"))).scalar_one()
                row.tool_scopes_json = json.dumps([{"name": "L", "tool_key": "list_appointments", "governance": "enabled", "description": ""}])
                await s.commit()
        run(read_only_tools())
        r = ask(world, "a_employee", "Show appointments")   # employee: no admin-only platform tool, so the read-only simple path
        assert r.status_code == 200 and r.json()["plan_id"] is None

        async def n():
            async with world.maker() as s:
                return len((await s.execute(select(AgentMemory))).scalars().all())
        assert run(n()) == 0

    def test_update_action_is_governed_and_tenant_scoped(self, world):
        from app.actions.registry import ACTION_REGISTRY
        act = ACTION_REGISTRY["update_appointment_status"]
        assert act.meta.requires_approval is True
        a = make(world)
        async def go(tenant, st, **kw):
            async with world.maker() as s:
                out = await act.execute({"appointment_id": a["id"], "status": st, **kw}, tenant, "MEDICAL_ASSISTANT", s)
                await s.commit()
                return out
        assert "not found" in run(go(world.tenant_b, "cancelled"))["message"].lower()
        assert run(go(world.tenant_a, "completed"))["success"] is False                      # requested -> completed is illegal
        assert run(go(world.tenant_a, "confirmed", scheduled_for=future()))["success"] is True
        assert act.validate({"appointment_id": "x", "status": "prescribe"})[0] is False
