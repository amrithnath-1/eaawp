"""
Settings changes asked in plain words (nobody names a tool), more settings reachable by chat, and the model is told who
it is talking to. Refusals are not remembered.

FAKED: the language model only. The chat planner below ALWAYS answers with a single response step (as the real model
did when it refused); the request must still become an approval-gated change.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.models import AIEmployee, User
from app.services.platform_requests import is_refusal, looks_like_settings_change
from tests.conftest import _run
from tests.test_role_intelligence import Recorder, ask, pick

DMM = "DIGITAL_MARKETING_MANAGER"
PLAIN = "Add Passport Services and Travel and Transport Services to our services"


class Model(Recorder):
    """Chat planner never proposes a tool; the customization planner returns `ops` / `missing`."""

    def __init__(self, ops, missing=()):
        super().__init__()
        self.ops, self.missing = ops, list(missing)
        self.customization_calls = 0

    async def ainvoke(self, messages, *a, **k):
        system = str(messages[0].content)
        if "Admin AI Customization Planner" in system:
            self.customization_calls += 1
            self.humans.append(str(messages[-1].content))
            return AIMessage(content=json.dumps({"summary": "Proposed changes", "operations": self.ops,
                                                 "missing_information": self.missing}))
        return await super().ainvoke(messages, *a, **k)


SERVICES = [{"type": "UPDATE_COMPANY_PROFILE", "description": "Add two services",
             "params": {"services": [{"name": "Passport Services", "description": "", "audience": ""},
                                     {"name": "Travel and Transport Services", "description": "", "audience": ""}]}}]


@pytest.fixture()
def llm(monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway
    holder = {"m": Model(SERVICES)}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


def approve(world, plan_id):
    r = world.client.post(f"/api/v1/planning/plans/{plan_id}/resume", json={"plan_id": plan_id},
                          headers=world.auth("a_admin"))
    assert r.status_code == 200, r.text
    return r.json()


def services(world):
    p = world.client.get("/api/v1/company-profile", headers=world.auth("a_admin")).json()["profile"]
    return [s["name"] for s in p["services"]]


def test_plain_words_become_an_approval_even_when_the_chat_model_would_not_use_the_tool(world, llm):
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", PLAIN, DMM).json()
    assert body["plan_status"] == "awaiting_approval", body
    assert "Proposed changes (nothing has been saved yet)" in body["message"]
    assert services(world) == []
    plan = approve(world, body["plan_id"])
    assert plan["status"] == "completed"
    assert services(world) == ["Passport Services", "Travel and Transport Services"]


def test_missing_details_are_asked_for_and_nothing_is_proposed(world, llm):
    llm["m"] = Model([], missing=["Which email address should be invited?"])
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", "Invite our new accountant as a team member", DMM).json()
    assert "Which email address should be invited?" in body["message"]
    assert body["plan_status"] is None
    assert world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json() == []


def test_a_false_alarm_falls_back_to_the_normal_planner(world, llm):
    llm["m"] = Model([])
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", "Give the team access to the Onam campaign report", DMM).json()
    assert body["plan_status"] == "completed" and body["message"] == "Here is my answer."


def test_the_conversation_gives_context_to_the_change(world, llm):
    pick(world, "a_admin", DMM)
    first = ask(world, "a_admin", "We now offer Passport Services and Travel and Transport Services.", DMM).json()
    body = {"blueprint": {"agent_id": "cabin", "role_name": "Digital Marketing Manager", "role_key": DMM,
                          "system_persona": "x", "allowed_tools": [], "guarded_tools": [],
                          "tenant_id": world.users["a_admin"]["tenant_id"]},
            "user_prompt": "Add those to our company profile", "conversation_id": first["conversation_id"]}
    r = world.client.post("/api/v1/agent/execute", json=body, headers=world.auth("a_admin")).json()
    assert r["plan_status"] == "awaiting_approval"
    assert "We now offer Passport Services" in llm["m"].humans[-1]        # earlier turn reached the change planner


def test_employees_are_told_an_administrator_can_do_it_and_get_no_tool(world, llm):
    pick(world, "a_employee", DMM)
    body = ask(world, "a_employee", PLAIN, DMM).json()
    assert body["plan_status"] != "awaiting_approval"
    assert llm["m"].customization_calls == 0
    planner = next(s for s in llm["m"].systems if "planning assistant" in s)
    assert "They are not an administrator" in planner


def test_administrators_are_told_they_are_administrators(world, llm):
    pick(world, "a_admin", DMM)
    ask(world, "a_admin", "Prepare a monthly marketing report", DMM)
    planner = next(s for s in llm["m"].systems if "planning assistant" in s)
    assert "company ADMINISTRATOR" in planner and "Never tell them to ask an administrator" in planner
    human = next(h for h, s in zip(llm["m"].humans, llm["m"].systems) if "planning assistant" in s)
    assert "customize_eaawp  [action: Change EAAWP's own settings" in human
    assert "fetch_knowledge_base  [read: Search the company knowledge base" in human


def test_refusals_are_not_remembered(world, monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway

    class Refuser(Recorder):
        async def ainvoke(self, messages, *a, **k):
            r = await super().ainvoke(messages, *a, **k)
            if r.content == "Here is my answer.":
                return AIMessage(content="That falls outside my responsibilities. A company administrator can do it.")
            return r
    m = Refuser()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: m)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    pick(world, "a_employee", DMM)
    ask(world, "a_employee", "Prepare the Onam campaign budget sheet", DMM)

    async def count():
        from app.db.memory_models import AgentMemory
        async with world.maker() as s:
            return len((await s.execute(select(AgentMemory).where(AgentMemory.tenant_id == world.tenant_a))).scalars().all())
    assert _run(count()) == 0


def test_detector():
    for yes in [PLAIN, "Change the tagline to We Handle the Process", "Call yourself Mira from now on",
                "Pause the institutional clerk", "make priya@example.com a manager", "Turn off notification emails",
                "Require approval before sending any email", "Create a Monday 9am marketing report workflow"]:
        assert looks_like_settings_change(yes), yes
    for no in ["Prepare a monthly marketing report", "How do I change the tagline?", "Make the email tone friendlier",
               "Write a blog post about passport services", "Create a campaign for Onam", "What are our services?",
               "Suggest a tagline for the Onam campaign", "Create a marketing objective for Q4 reach"]:
        assert not looks_like_settings_change(no), no
    assert is_refusal("Updating the company profile falls outside my responsibilities. A company administrator can.")
    assert not is_refusal("Here are three campaign ideas for Onam.")


# ── More settings by chat ────────────────────────────────────────────────────

def _change(world, llm, ops, prompt):
    llm["m"] = Model(ops)
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", prompt, DMM).json()
    assert body["plan_status"] == "awaiting_approval", body
    return approve(world, body["plan_id"])


def test_team_role_change_is_made_as_the_approving_administrator(world, llm):
    plan = _change(world, llm, [{"type": "CHANGE_TEAM_ROLE", "description": "Make the employee a manager",
                                 "params": {"email": "a_employee@example.test", "role": "Manager"}}],
                   "make a_employee@example.test a manager")
    assert plan["status"] == "completed", plan

    async def role():
        async with world.maker() as s:
            return (await s.get(User, world.users["a_employee"]["id"])).role
    assert _run(role()) == "Manager"


def test_invitation_link_never_appears_in_chat(world, llm):
    plan = _change(world, llm, [{"type": "INVITE_TEAM_MEMBER", "description": "Invite Ravi",
                                 "params": {"email": "ravi@example.test", "role": "Employee"}}],
                   "Invite ravi@example.test as an employee")
    step = next(s for s in plan["steps"] if s["tool_name"] == "customize_eaawp")
    assert "Invitation created for ravi@example.test" in step["result_summary"]
    assert "token" not in step["result_summary"].lower() and "http" not in step["result_summary"]
    inv = world.client.get("/api/v1/team/invitations", headers=world.auth("a_admin"))
    assert inv.status_code == 200 and "ravi@example.test" in inv.text


def test_pause_an_ai_employee_and_switch_a_module_off(world, llm):
    async def seed():
        async with world.maker() as s:
            s.add(AIEmployee(tenant_id=world.tenant_a, role_key="INSTITUTIONAL_CLERK", name="Clerk", status="ACTIVE"))
            await s.commit()
    _run(seed())
    plan = _change(world, llm, [
        {"type": "SET_AI_EMPLOYEE_PAUSED", "description": "Pause the clerk",
         "params": {"role_key": "INSTITUTIONAL_CLERK", "paused": True}},
        {"type": "SET_MODULE_ACTIVE", "description": "Deactivate the medical module",
         "params": {"module_key": "MEDICAL_ASSISTANT", "active": False}}],
        "Pause the institutional clerk and deactivate the medical assistant module")
    assert plan["status"] == "completed", plan
    step = next(s for s in plan["steps"] if s["tool_name"] == "customize_eaawp")
    assert "2 saved" in step["result_summary"], step

    async def status():
        async with world.maker() as s:
            return (await s.execute(select(AIEmployee.status).where(AIEmployee.tenant_id == world.tenant_a))).scalar_one()
    assert _run(status()) == "PAUSED"
    mods = {m["key"]: m for m in world.client.get("/api/v1/modules", headers=world.auth("a_admin")).json()}
    assert mods["MEDICAL_ASSISTANT"]["active"] is False


def test_unavailable_changes_are_reported_not_faked(world, llm):
    plan = _change(world, llm, [
        {"type": "SET_INTEGRATION_ENABLED", "description": "Switch GitHub off",
         "params": {"provider_type": "github", "enabled": False}},
        {"type": "SET_NOTIFICATION_EMAILS", "description": "Turn notification emails on", "params": {"enabled": True}}],
        "Switch off the GitHub integration and turn on notification emails")
    step = next(s for s in plan["steps"] if s["tool_name"] == "customize_eaawp")
    assert "0 saved, 2 failed" in step["result_summary"], step
