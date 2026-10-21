"""
Institutional Clerk (Phase H): service requests, review workflow, documents, extraction, agent tools.
REAL: API, auth, tenancy, state machine, DB, template engine, tool/action code. FAKED: the LLM only.
"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.clerk_models import IssuedDocument, ServiceRequest
from app.db.models import AuditLog
from app.services import clerk_service as cs
from tests.test_marketing_analytics_e2e import run

API = "/api/v1/clerk"


def req(world, who="a_employee", **over):
    body = {"request_type": "certificate", "title": "Bonafide for bank", "details": "Need it for a loan", **over}
    return world.client.post(f"{API}/requests", json=body, headers=world.auth(who))


def make(world, who="a_employee", **over):
    r = req(world, who, **over)
    assert r.status_code == 201, r.text
    return r.json()


def status(world, rid, to, note="", who="a_admin"):
    return world.client.post(f"{API}/requests/{rid}/status", json={"status": to, "note": note}, headers=world.auth(who))


class Model:
    def __init__(self, h):
        self.h = h

    def bind_tools(self, t):
        return self

    async def ainvoke(self, messages, *a, **k):
        if "extract details from an administrative document" in str(messages[0].content):
            return AIMessage(content=self.h.extracted if isinstance(self.h.extracted, str) else json.dumps(self.h.extracted))
        return AIMessage(content="{}")


@pytest.fixture()
def llm(monkeypatch):
    from app.llm.gateway import LLMGateway
    h = SimpleNamespace(extracted={"full_name": "Asha Verma", "id_number": "CS-2041", "purpose": "Bank loan"}, ready=True)
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: Model(h))
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: Model(h))
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=h.ready))
    return h


# ── submitting & visibility ──────────────────────────────────────────────────────

class TestSubmitAndVisibility:
    def test_member_submits_and_sees_timeline(self, world):
        r = make(world)
        assert r["status"] == "submitted" and r["requester_name"] and [e["kind"] for e in r["events"]] == ["created"]

    @pytest.mark.parametrize("over,fragment", [
        ({"request_type": "nuclear"}, "Unknown request type"),
        ({"title": "  x "}, "title"),
        ({"priority": "urgent!!"}, "Priority"),
        ({"due_date": "31/12/2026"}, "Due date"),
        ({"fields": {"Bad Name": "x"}}, "Invalid field name"),
    ])
    def test_invalid_input_is_refused_clearly(self, world, over, fragment):
        r = req(world, **over)
        assert r.status_code == 422 and fragment in json.dumps(r.json())

    def test_open_request_cap(self, world, monkeypatch):
        for i in range(25):
            assert req(world, title=f"Request number {i}").status_code == 201
        assert req(world, title="One too many").status_code == 429

    def test_members_see_only_their_own_admin_sees_all(self, world):
        mine = make(world, who="a_employee", title="Employee request")
        theirs = make(world, who="a_admin", title="Admin request")
        emp = world.client.get(f"{API}/requests", headers=world.auth("a_employee")).json()
        assert [r["id"] for r in emp] == [mine["id"]]
        assert {r["id"] for r in world.client.get(f"{API}/requests", headers=world.auth("a_admin")).json()} == {mine["id"], theirs["id"]}
        assert world.client.get(f"{API}/requests/{theirs['id']}", headers=world.auth("a_employee")).status_code == 404

    def test_other_company_gets_404_everywhere(self, world):
        r = make(world)
        h = world.auth("b_admin")
        assert world.client.get(f"{API}/requests", headers=h).json() == []
        for call in (lambda: world.client.get(f"{API}/requests/{r['id']}", headers=h),
                     lambda: status(world, r["id"], "in_review", who="b_admin"),
                     lambda: world.client.post(f"{API}/requests/{r['id']}/comments", json={"body": "hi"}, headers=h),
                     lambda: world.client.post(f"{API}/requests/{r['id']}/assign", json={"assignee_id": None}, headers=h),
                     lambda: world.client.post(f"{API}/documents", json={"template_key": "notice", "request_id": r["id"], "fields": {"heading": "h", "message": "m"}}, headers=h)):
            assert call().status_code == 404

    def test_unauthenticated_is_rejected(self, world):
        assert world.client.get(f"{API}/requests").status_code == 401


# ── review workflow ──────────────────────────────────────────────────────────────

class TestWorkflow:
    def test_only_admins_change_status_or_assign(self, world):
        r = make(world)
        assert status(world, r["id"], "approved", who="a_employee").status_code == 403
        assert world.client.post(f"{API}/requests/{r['id']}/assign", json={"assignee_id": None}, headers=world.auth("a_employee")).status_code == 403

    def test_full_happy_path_records_a_timeline_and_audit(self, world):
        r = make(world)
        assert status(world, r["id"], "in_review").status_code == 200
        d = status(world, r["id"], "approved", "Verified against records").json()
        assert d["status"] == "approved" and d["decision_note"] == "Verified against records" and d["decided_at"]
        d = status(world, r["id"], "fulfilled").json()
        assert d["status"] == "fulfilled"
        assert [e["kind"] for e in d["events"]].count("status") == 3
        async def ev():
            async with world.maker() as s:
                return " | ".join(a.event for a in (await s.execute(select(AuditLog))).scalars().all())
        assert "submitted" in run(ev()) and "in_review -> approved" in run(ev())

    @pytest.mark.parametrize("path", [("approved", "in_review"), ("rejected", "approved"), ("approved", "rejected"), ("fulfilled", "in_review")])
    def test_illegal_transitions_are_409(self, world, path):
        r = make(world)
        first, second = path
        if first == "fulfilled":
            status(world, r["id"], "approved"); status(world, r["id"], "fulfilled")
        else:
            status(world, r["id"], first, "because")
        assert status(world, r["id"], second, "again").status_code == 409

    def test_reject_and_needs_info_require_a_reason(self, world):
        r = make(world)
        assert status(world, r["id"], "rejected").status_code == 422
        assert status(world, r["id"], "needs_info").status_code == 422
        assert status(world, r["id"], "needs_info", "Please send your ID number").json()["status"] == "needs_info"

    def test_requester_reply_moves_needs_info_back_to_review(self, world):
        r = make(world)
        status(world, r["id"], "needs_info", "Which semester?")
        d = world.client.post(f"{API}/requests/{r['id']}/comments", json={"body": "Semester 5"}, headers=world.auth("a_employee")).json()
        assert d["status"] == "in_review" and d["events"][-1]["body"].startswith("needs info -> in review")

    def test_closed_request_cannot_be_commented(self, world):
        r = make(world)
        status(world, r["id"], "rejected", "Not eligible")
        assert world.client.post(f"{API}/requests/{r['id']}/comments", json={"body": "pls"}, headers=world.auth("a_employee")).status_code == 409

    def test_internal_notes_are_invisible_to_the_requester(self, world):
        r = make(world)
        assert world.client.post(f"{API}/requests/{r['id']}/comments", json={"body": "secret", "internal": True}, headers=world.auth("a_employee")).status_code == 403
        world.client.post(f"{API}/requests/{r['id']}/comments", json={"body": "Possible duplicate of last year", "internal": True}, headers=world.auth("a_admin"))
        emp = world.client.get(f"{API}/requests/{r['id']}", headers=world.auth("a_employee")).json()
        assert "duplicate" not in json.dumps(emp)
        assert "duplicate" in json.dumps(world.client.get(f"{API}/requests/{r['id']}", headers=world.auth("a_admin")).json())

    def test_requester_can_cancel_own_open_request_only(self, world):
        r = make(world)
        other = make(world, who="a_admin")
        assert world.client.post(f"{API}/requests/{other['id']}/cancel", headers=world.auth("a_employee")).status_code == 404
        assert world.client.post(f"{API}/requests/{r['id']}/cancel", headers=world.auth("a_employee")).json()["status"] == "cancelled"
        r2 = make(world); status(world, r2["id"], "approved")
        assert world.client.post(f"{API}/requests/{r2['id']}/cancel", headers=world.auth("a_employee")).status_code == 409

    def test_admin_uses_status_not_the_requester_cancel_endpoint(self, world):
        r = make(world)
        denied = world.client.post(f"{API}/requests/{r['id']}/cancel", headers=world.auth("a_admin"))
        assert denied.status_code == 403 and "Only the person who made the request" in denied.json()["detail"]
        assert status(world, r["id"], "cancelled").json()["status"] == "cancelled"

    def test_assignment_validates_company_membership_and_starts_review(self, world):
        r = make(world)
        admin_id = world.users["a_admin"]["id"]
        bad = world.client.post(f"{API}/requests/{r['id']}/assign", json={"assignee_id": "nobody"}, headers=world.auth("a_admin"))
        assert bad.status_code == 404
        ok = world.client.post(f"{API}/requests/{r['id']}/assign", json={"assignee_id": admin_id}, headers=world.auth("a_admin")).json()
        assert ok["assignee_id"] == admin_id and ok["status"] == "in_review"
        b_admin = world.users["b_admin"]["id"]
        assert world.client.post(f"{API}/requests/{r['id']}/assign", json={"assignee_id": b_admin}, headers=world.auth("a_admin")).status_code == 404


# ── documents ────────────────────────────────────────────────────────────────────

BONAFIDE = {"full_name": "Asha Verma", "id_number": "CS-2041", "purpose": "Bank loan"}


def draft(world, rid=None, fields=None, who="a_admin", key="bonafide"):
    return world.client.post(f"{API}/documents", json={"template_key": key, "fields": BONAFIDE if fields is None else fields, "request_id": rid},
                             headers=world.auth(who))


class TestDocuments:
    def test_draft_issue_download_flow_with_unique_serials(self, world):
        r = make(world); status(world, r["id"], "approved")
        d = draft(world, r["id"]).json()
        assert d["status"] == "draft" and d["serial"] is None and "Asha Verma" in d["body"] and "(assigned when issued)" in d["body"]
        # the requester must not see a draft
        assert world.client.get(f"{API}/documents/{d['id']}/download", headers=world.auth("a_employee")).status_code == 404
        assert world.client.get(f"{API}/requests/{r['id']}", headers=world.auth("a_employee")).json()["documents"] == []
        i = world.client.post(f"{API}/documents/{d['id']}/issue", headers=world.auth("a_admin")).json()
        assert i["status"] == "issued" and i["serial"].endswith("-00001") and i["serial"] in i["body"]
        d2 = draft(world, None).json()
        assert world.client.post(f"{API}/documents/{d2['id']}/issue", headers=world.auth("a_admin")).json()["serial"].endswith("-00002")
        got = world.client.get(f"{API}/documents/{d['id']}/download", headers=world.auth("a_employee"))
        assert got.status_code == 200 and "Asha Verma" in got.text and "attachment" in got.headers["content-disposition"]
        assert [x["serial"] for x in world.client.get(f"{API}/requests/{r['id']}", headers=world.auth("a_employee")).json()["documents"]] == [i["serial"]]

    def test_issue_twice_is_409_and_void_needs_reason(self, world):
        d = draft(world).json()
        world.client.post(f"{API}/documents/{d['id']}/issue", headers=world.auth("a_admin"))
        assert world.client.post(f"{API}/documents/{d['id']}/issue", headers=world.auth("a_admin")).status_code == 409
        assert world.client.post(f"{API}/documents/{d['id']}/void", json={"reason": "x"}, headers=world.auth("a_admin")).status_code == 422
        v = world.client.post(f"{API}/documents/{d['id']}/void", json={"reason": "Wrong name"}, headers=world.auth("a_admin")).json()
        assert v["status"] == "void" and "VOID" in v["body"]

    def test_only_admins_draft_issue_void_or_list(self, world):
        assert draft(world, who="a_employee").status_code == 403
        d = draft(world).json()
        for call in (lambda: world.client.post(f"{API}/documents/{d['id']}/issue", headers=world.auth("a_employee")),
                     lambda: world.client.post(f"{API}/documents/{d['id']}/void", json={"reason": "abc"}, headers=world.auth("a_employee")),
                     lambda: world.client.get(f"{API}/documents", headers=world.auth("a_employee"))):
            assert call().status_code == 403

    def test_requester_cannot_download_someone_elses_issued_document(self, world):
        other = make(world, who="a_admin")
        d = draft(world, other["id"]).json()
        world.client.post(f"{API}/documents/{d['id']}/issue", headers=world.auth("a_admin"))
        assert world.client.get(f"{API}/documents/{d['id']}/download", headers=world.auth("a_employee")).status_code == 404
        assert world.client.get(f"{API}/documents/{d['id']}/download", headers=world.auth("b_admin")).status_code == 404

    def test_serials_are_per_company(self, world):
        a = draft(world).json(); b = draft(world, who="b_admin").json()
        sa = world.client.post(f"{API}/documents/{a['id']}/issue", headers=world.auth("a_admin")).json()["serial"]
        sb = world.client.post(f"{API}/documents/{b['id']}/issue", headers=world.auth("b_admin")).json()["serial"]
        assert sa.endswith("-00001") and sb.endswith("-00001")

    def test_missing_required_fields_and_unknown_template(self, world):
        r = draft(world, fields={"full_name": "Only Name"})
        assert r.status_code == 422 and "ID / roll number" in r.json()["detail"]
        assert draft(world, key="nuclear_codes").status_code == 422

    def test_template_values_cannot_expand_into_tokens_or_inject_controls(self):
        out = cs.render("bonafide", {"full_name": "{{institution}}", "id_number": "1\x00\x07", "purpose": "{{full_name}}"}, "Acme College", None)
        assert "{{institution}}" in out and "{{full_name}}" in out and "\x00" not in out and "\x07" not in out

    def test_document_for_request_in_another_company_is_404(self, world):
        r = make(world)
        assert draft(world, r["id"], who="b_admin").status_code == 404


# ── extraction ───────────────────────────────────────────────────────────────────

def extract(world, data=b"Student Asha Verma, ID CS-2041, applies for a letter for a Bank loan.", name="form.txt", who="a_admin"):
    return world.client.post(f"{API}/extract", files={"file": (name, io.BytesIO(data), "text/plain")}, headers=world.auth(who))


class TestExtraction:
    def test_returns_only_values_found_verbatim_in_the_document(self, world, llm):
        llm.extracted = {"full_name": "Asha Verma", "id_number": "CS-9999", "purpose": "bank LOAN", "ssn": "123", "to_date": ["x"]}
        r = extract(world).json()
        assert r["fields"] == {"full_name": "Asha Verma", "purpose": "bank LOAN"} and "id_number" in r["dropped"]

    def test_bad_inputs(self, world, llm):
        assert extract(world, name="x.exe").status_code == 422
        assert "No readable text" in extract(world, data=b"hi").json()["detail"]
        llm.extracted = "not json"
        assert extract(world).status_code == 422
        llm.ready = False
        assert extract(world).status_code == 503

    def test_admin_only(self, world, llm):
        assert extract(world, who="a_employee").status_code == 403


# ── agent tools / actions ────────────────────────────────────────────────────────

class TestAgentSide:
    def test_actions_are_registered_with_the_right_governance(self):
        from app.actions.registry import ACTION_REGISTRY
        assert ACTION_REGISTRY["draft_service_document"].meta.requires_approval is False
        assert ACTION_REGISTRY["update_service_request"].meta.requires_approval is True

    def test_update_action_uses_the_state_machine_and_tenant_scope(self, world):
        from app.actions.registry import ACTION_REGISTRY
        r = make(world)
        act = ACTION_REGISTRY["update_service_request"]
        async def go(tenant, rid, st, note=""):
            async with world.maker() as s:
                out = await act.execute({"request_id": rid, "status": st, "note": note}, tenant, "INSTITUTIONAL_CLERK", s)
                await s.commit()
                return out
        assert "not found" in run(go(world.tenant_b, r["id"], "in_review"))["message"].lower()
        assert run(go(world.tenant_a, r["id"], "in_review"))["success"] is True
        bad = run(go(world.tenant_a, r["id"], "fulfilled"))
        assert bad["success"] is False and "cannot become" in bad["message"]
        assert act.validate({"request_id": "x", "status": "deleted_everything"})[0] is False
        det = world.client.get(f"{API}/requests/{r['id']}", headers=world.auth("a_admin")).json()
        assert det["events"][-1]["actor_name"].startswith("INSTITUTIONAL_CLERK")

    def test_draft_action_creates_a_draft_only(self, world):
        from app.actions.registry import ACTION_REGISTRY
        act = ACTION_REGISTRY["draft_service_document"]
        async def go(fields):
            async with world.maker() as s:
                out = await act.execute({"template_key": "bonafide", "fields": fields}, world.tenant_a, "INSTITUTIONAL_CLERK", s)
                await s.commit()
                return out
        assert run(go({"full_name": "x"}))["success"] is False
        ok = run(go(BONAFIDE))
        assert ok["success"] is True and "not issued" in ok["message"]
        docs = world.client.get(f"{API}/documents", headers=world.auth("a_admin")).json()
        assert docs[0]["status"] == "draft" and docs[0]["serial"] is None

    def test_read_tools_respect_who_is_asking(self, world):
        from app.tools import registry
        mine = make(world, who="a_employee", title="Employee own request")
        other = make(world, who="a_admin", title="Admin private request")
        emp_id = world.users["a_employee"]["id"]
        async def call(tool, params, user_id, is_admin, tenant):
            async with world.maker() as s:
                registry.set_tool_context(db_session=s, tenant_id=tenant, role_key="INSTITUTIONAL_CLERK", user_id=user_id, is_admin=is_admin)
                try:
                    return await registry.MASTER_TOOL_REGISTRY[tool].ainvoke({"params": params})
                finally:
                    registry.clear_tool_context()
        as_emp = run(call("list_service_requests", "{}", emp_id, False, world.tenant_a))
        assert "Employee own request" in as_emp and "Admin private request" not in as_emp
        as_admin = run(call("list_service_requests", "{}", "someone-admin", True, world.tenant_a))
        assert "Employee own request" in as_admin and "Admin private request" in as_admin
        assert "Admin private request" not in run(call("get_service_request", json.dumps({"request_id": other["id"]}), emp_id, False, world.tenant_a))
        assert "not found" in run(call("get_service_request", json.dumps({"request_id": mine["id"]}), "x", False, world.tenant_b)).lower()
        assert "No requests" in run(call("list_service_requests", "{}", "u", True, world.tenant_b))

    def test_clerk_role_is_available_with_safe_defaults(self, world):
        r = world.client.get("/api/v1/roles/INSTITUTIONAL_CLERK", headers=world.auth("a_admin"))
        assert r.status_code == 200, r.text
        scopes = {t["tool_key"]: t["governance"] for t in r.json()["tool_scopes"]}
        assert scopes["update_service_request"] == "requires_approval" and scopes["draft_service_document"] == "enabled"
        assert "send_email" not in scopes


# ── through the real agent pipeline ─────────────────────────────────────────────

SEEN: list[str] = []


class PipelineModel:
    def bind_tools(self, t):
        return self

    async def ainvoke(self, messages, *a, **k):
        system, human = str(messages[0].content), str(messages[-1].content)
        SEEN.append(system + "\n" + human)
        if "planning assistant" in system:
            return AIMessage(content=json.dumps({"objective": "List requests", "steps": [
                {"step_index": 0, "step_type": "read", "description": "List the requests", "tool_name": "list_service_requests",
                 "arguments": {"params": "{}"}, "depends_on": []},
                {"step_index": 1, "step_type": "response", "description": "Report", "tool_name": None, "arguments": {}, "depends_on": [0]}]}))
        if "Information gathered" in human:
            return AIMessage(content="Here are the requests:\n" + human.split("Information gathered:\n", 1)[1].split("\n\nUsing the information", 1)[0])
        return AIMessage(content='{"intent_type": "UNKNOWN", "confidence": 0.0, "reasoning": "n/a"}')


class TestClerkThroughThePipeline:
    @staticmethod
    def ask(world, who):
        from app.db.models import Company  # noqa: F401
        body = {"blueprint": {"agent_id": "clerk-1", "role_name": "Institutional Clerk", "role_key": "INSTITUTIONAL_CLERK",
                              "system_persona": "You are the clerk.", "allowed_tools": [], "guarded_tools": [],
                              "tenant_id": world.users[who]["tenant_id"]},
                "user_prompt": "What requests do we have right now?"}
        return world.client.post("/api/v1/agent/execute", json=body, headers=world.auth(who))

    def test_the_asker_decides_what_the_agent_can_see(self, world, monkeypatch):
        from app.llm.gateway import LLMGateway
        monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: PipelineModel())
        monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: PipelineModel())
        monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
        make(world, who="a_employee", title="Employee leave request", request_type="leave")
        make(world, who="a_admin", title="Admin salary query", request_type="fee_query")
        emp = self.ask(world, "a_employee")
        assert emp.status_code == 200, emp.text
        assert "Employee leave request" in emp.text and "Admin salary query" not in emp.text
        adm = self.ask(world, "a_admin")
        assert adm.status_code == 200 and "Employee leave request" in adm.text and "Admin salary query" in adm.text
        other = self.ask(world, "b_admin")
        assert "Employee leave request" not in other.text and "Admin salary query" not in other.text

    def test_clerk_conversations_are_never_written_to_shared_memory(self, world, monkeypatch):
        """Agent memory is shared by every user of a company+role; for personal-record roles nothing may be stored.
        (Read-only tool set => the simple execution path, which is the one that stores memory for other roles.)"""
        from app.db.memory_models import AgentMemory
        from app.db.models import RoleConfiguration
        from app.llm.gateway import LLMGateway
        monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: PipelineModel())
        monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: PipelineModel())
        monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
        make(world, who="a_admin", title="Confidential grievance about a teacher", request_type="complaint")
        assert world.client.get("/api/v1/roles/INSTITUTIONAL_CLERK", headers=world.auth("a_admin")).status_code == 200   # seeds the role

        async def read_only_tools():
            async with world.maker() as s:
                row = (await s.execute(select(RoleConfiguration).where(RoleConfiguration.tenant_id == world.tenant_a,
                                                                       RoleConfiguration.role_key == "INSTITUTIONAL_CLERK"))).scalar_one()
                row.tool_scopes_json = json.dumps([{"name": "L", "tool_key": "list_service_requests", "governance": "enabled", "description": ""}])
                await s.commit()
        run(read_only_tools())
        r = self.ask(world, "a_admin")
        assert r.status_code == 200 and r.json()["plan_id"] is None          # simple path

        async def n():
            async with world.maker() as s:
                return len((await s.execute(select(AgentMemory))).scalars().all())
        assert run(n()) == 0
