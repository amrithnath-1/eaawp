"""
Administrators can change EAAWP itself by asking ANY AI employee in the chat. The concrete changes are prepared and
shown for approval first; nothing is saved before approval; the result says what was saved. Employees never get the
tool.

FAKED: the language model (planner + customization planner) only.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.models import RoleConfiguration
from tests.conftest import _run
from tests.test_role_intelligence import Recorder, ask, pick

DMM = "DIGITAL_MARKETING_MANAGER"
REQUEST = ("Update the approved company profile for GEC Services: add the services Passport Services and "
           "Travel and Transport Services, and set the tagline to 'We Handle the Process. You Own Your Time.'")


class Scripted(Recorder):
    """Planner proposes customize_eaawp; the customization planner returns `ops`."""

    def __init__(self, ops):
        super().__init__()
        self.ops = ops

    async def ainvoke(self, messages, *a, **k):
        system, human = str(messages[0].content), str(messages[-1].content)
        if "Admin AI Customization Planner" in system:
            self.systems.append(system)
            self.humans.append(human)
            return AIMessage(content=json.dumps({"summary": "Proposed EAAWP changes", "operations": self.ops,
                                                 "missing_information": []}))
        if "planning assistant" in system:
            self.systems.append(system)
            self.humans.append(human)
            if "customize_eaawp" not in human:      # the tool was not offered to this person
                return AIMessage(content=json.dumps({"objective": "x", "steps": [
                    {"step_index": 0, "step_type": "response", "description": "Answer", "tool_name": None,
                     "arguments": {}, "depends_on": []}]}))
            req = human.rsplit("User request:", 1)[-1].strip()
            return AIMessage(content=json.dumps({"objective": "change EAAWP", "steps": [
                {"step_index": 0, "step_type": "read",   # mislabelled on purpose: must still go through governance
                 "description": "Propose the requested change", "tool_name": "customize_eaawp",
                 "arguments": {"instruction": req}, "depends_on": []},
                {"step_index": 1, "step_type": "response", "description": "Report", "tool_name": None,
                 "arguments": {}, "depends_on": [0]}]}))
        return await super().ainvoke(messages, *a, **k)


PROFILE_OPS = [{"type": "UPDATE_COMPANY_PROFILE", "description": "Add two services and set the tagline",
                "params": {"tagline": "We Handle the Process. You Own Your Time.",
                           "services": [{"name": "Passport Services", "description": "", "audience": ""},
                                        {"name": "Travel and Transport Services", "description": "", "audience": ""}]}}]


@pytest.fixture()
def scripted(monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway
    holder = {"rec": Scripted(PROFILE_OPS)}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["rec"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["rec"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


def profile(world, who="a_admin"):
    return world.client.get("/api/v1/company-profile", headers=world.auth(who)).json()["profile"]


def approve(world, plan_id):
    r = world.client.post(f"/api/v1/planning/plans/{plan_id}/resume", json={"plan_id": plan_id},
                          headers=world.auth("a_admin"))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("role", [DMM, "MEDICAL_ASSISTANT"])
def test_admin_changes_the_company_profile_by_chat_only_after_approval(world, scripted, role):
    world.client.put("/api/v1/company-profile", json={"brand_name": "GEC Services", "website": "gecservices.in",
                                                       "services": [{"name": "Website Design", "description": "Sites",
                                                                     "audience": "SMEs"}]},
                     headers=world.auth("a_admin"))
    pick(world, "a_admin", role)
    body = ask(world, "a_admin", REQUEST, role).json()
    assert body["plan_status"] == "awaiting_approval", body
    assert "Proposed changes (nothing has been saved yet)" in body["message"]
    assert "Passport Services" in body["message"]
    assert profile(world)["tagline"] == ""                        # nothing saved before approval

    plan = approve(world, body["plan_id"])
    assert plan["status"] == "completed", plan
    p = profile(world)
    assert p["tagline"] == "We Handle the Process. You Own Your Time."
    assert [s["name"] for s in p["services"]] == ["Website Design", "Passport Services", "Travel and Transport Services"]
    assert p["services"][0]["description"] == "Sites"             # existing information kept
    assert p["brand_name"] == "GEC Services" and p["website"] == "https://gecservices.in"
    step = next(s for s in plan["steps"] if s["tool_name"] == "customize_eaawp")
    assert step["step_type"] == "action" and "1 saved" in step["result_summary"]


def test_rejecting_changes_nothing(world, scripted):
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", REQUEST, DMM).json()
    r = world.client.post(f"/api/v1/planning/plans/{body['plan_id']}/reject", json={"plan_id": body["plan_id"]},
                          headers=world.auth("a_admin"))
    assert r.json()["status"] == "rejected"
    assert profile(world)["services"] == [] and profile(world)["tagline"] == ""


def test_approval_record_shows_the_exact_changes(world, scripted):
    pick(world, "a_admin", DMM)
    ask(world, "a_admin", REQUEST, DMM)
    a = world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json()[0]
    assert a["tool_name"] == "customize_eaawp" and a["ai_employee"] == "Digital Marketing Manager"
    assert "Travel and Transport Services" in a["parameters"]["changes"]


def test_employees_are_not_offered_the_tool_and_cannot_use_it(world, scripted):
    pick(world, "a_employee", DMM)
    body = ask(world, "a_employee", REQUEST, DMM).json()
    planner_calls = [h for h, s in zip(scripted["rec"].humans, scripted["rec"].systems) if "planning assistant" in s]
    assert planner_calls and all("customize_eaawp" not in h for h in planner_calls)
    assert body["plan_status"] != "awaiting_approval"
    assert world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json() == []

    from app.schemas.actions import ActionRequest
    from app.services.action_governance import process_action_request

    async def forced():
        async with world.maker() as s:
            return await process_action_request(
                ActionRequest(tool_name="customize_eaawp", arguments={"instruction": REQUEST},
                              tenant_id=world.tenant_a, role_key=DMM, requested_by="agent"),
                blueprint_allowed_tools=[], blueprint_guarded_tools=["send_email"], db=s)
    assert _run(forced()).status == "unauthorized"


def test_admin_renames_a_built_in_ai_employee_and_tools_stay_unchanged(world, scripted):
    scripted["rec"] = Scripted([{"type": "UPDATE_ROLE_SETTINGS", "description": "Rename and soften the tone",
                                 "params": {"role_key": DMM, "agent_name": "Mira", "communication_style": "Friendly",
                                            "quick_prompts": ["Plan this week's posts"]}}])
    pick(world, "a_admin", DMM)
    before = world.client.get(f"/api/v1/roles/{DMM}", headers=world.auth("a_admin")).json()
    body = ask(world, "a_admin", "Call the marketing assistant Mira and make it friendlier", DMM).json()
    approve(world, body["plan_id"])

    async def row():
        async with world.maker() as s:
            return (await s.execute(select(RoleConfiguration).where(
                RoleConfiguration.tenant_id == world.tenant_a, RoleConfiguration.role_key == DMM))).scalar_one()
    r = _run(row())
    assert (r.agent_name, r.communication_style, json.loads(r.quick_prompts_json)) == (
        "Mira", "Friendly", ["Plan this week's posts"])
    after = world.client.get(f"/api/v1/roles/{DMM}", headers=world.auth("a_admin")).json()
    assert after["tool_scopes"] == before["tool_scopes"]


def test_credentials_can_never_be_part_of_a_change(world, scripted):
    scripted["rec"] = Scripted([{"type": "CONNECT_INTEGRATION", "description": "Connect GitHub",
                                 "params": {"provider_type": "github", "api_key": "ghp_should_never_be_here"}}])
    pick(world, "a_admin", DMM)
    body = ask(world, "a_admin", "Connect GitHub with key ghp_should_never_be_here", DMM).json()
    assert body["plan_status"] != "awaiting_approval"
    assert world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json() == []


def test_charter_and_tool_status_describe_platform_administration(world):
    from app.services.role_charter import build_role_charter
    text = build_role_charter("MEDICAL_ASSISTANT", "Medical Assistant")
    assert "platform administration, not another AI employee's job" in text
    pick(world, "a_admin", DMM)
    pick(world, "a_employee", DMM)
    admin = world.client.get("/api/v1/workspace/tools", headers=world.auth("a_admin")).json()
    emp = world.client.get("/api/v1/workspace/tools", headers=world.auth("a_employee")).json()
    assert [t["key"] for t in admin["tools"] if t["source"] == "platform"] == ["customize_eaawp"]
    assert not [t for t in emp["tools"] if t["source"] == "platform"]


def test_unattended_runs_never_get_the_platform_tool(world, scripted):
    """Workflows and meetings call execute_agent directly (interactive=False): no reconfiguration from them."""
    from app.api.routers.execution import execute_agent
    from app.db.models import User
    from app.schemas.blueprint import AgentBlueprint, AgentExecutionRequest

    async def go():
        async with world.maker() as s:
            admin = await s.get(User, world.users["a_admin"]["id"])
            req = AgentExecutionRequest(blueprint=AgentBlueprint(agent_id="wf", role_name="Digital Marketing Manager",
                                                                 system_persona="x", tenant_id=world.tenant_a),
                                        user_prompt=REQUEST, session_id="workflow:test")
            return await execute_agent(request=req, tenant_id=world.tenant_a, db=s, user=admin)
    resp = _run(go())
    planner_calls = [h for h, s in zip(scripted["rec"].humans, scripted["rec"].systems) if "planning assistant" in s]
    assert planner_calls and all("customize_eaawp" not in h for h in planner_calls)
    assert resp.plan_status != "awaiting_approval"
