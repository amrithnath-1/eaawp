"""
The chat agent (interactive chat works like ChatGPT/Claude: the model calls tools itself and decides the next step).

FAKED: the language model only (a script of replies, including native tool calls) and GitHub's HTTP API.
Real: auth, workspaces, role configuration, tools, action governance, approvals, plans, conversations, database.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tests.conftest import _run
from tests.test_role_intelligence import _connect_github, ask, pick

DMM = "DIGITAL_MARKETING_MANAGER"


def call(name, args, cid="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


class Script:
    """Replies in order; every call's messages and the bound tool names are recorded."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[list] = []
        self.tools: list[str] = []
        self.customization = None

    def bind_tools(self, tools, *a, **k):
        self.tools = [getattr(t, "name", "") for t in tools]
        return self

    async def ainvoke(self, messages, *a, **k):
        system = str(messages[0].content)
        if "Admin AI Customization Planner" in system:
            return AIMessage(content=json.dumps(self.customization))
        self.calls.append(list(messages))
        if not self.replies:
            return AIMessage(content="Done.")
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt if isinstance(nxt, AIMessage) else AIMessage(content=nxt)


@pytest.fixture()
def agent(monkeypatch):
    from types import SimpleNamespace
    import app.config as cfg
    from app.llm.gateway import LLMGateway
    cfg.settings.__dict__["chat_engine"] = "agent"
    holder = {"m": Script("Hello! How can I help?")}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


def send(world, who, prompt, conversation_id=None):
    body = {"blueprint": {"agent_id": "cabin", "role_name": "Digital Marketing Manager", "role_key": DMM,
                          "system_persona": "x", "allowed_tools": [], "guarded_tools": [],
                          "tenant_id": world.users[who]["tenant_id"]},
            "user_prompt": prompt}
    if conversation_id:
        body["conversation_id"] = conversation_id
    r = world.client.post("/api/v1/agent/execute", json=body, headers=world.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_answers_directly_and_sees_the_conversation_as_real_messages(world, agent):
    agent["m"] = Script("We could run an Onam offer on passport renewals.", "Sure — a shorter version: Onam passport offer.")
    pick(world, "a_admin", DMM)
    first = send(world, "a_admin", "Give me one campaign idea for Onam")
    assert first["message"] == "We could run an Onam offer on passport renewals."
    assert first["plan_status"] == "completed"
    second = send(world, "a_admin", "make it shorter", first["conversation_id"])
    msgs = agent["m"].calls[-1]
    assert [type(m).__name__ for m in msgs] == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]
    assert msgs[1].content == "Give me one campaign idea for Onam" and "Onam offer" in msgs[2].content
    assert "How you work in this chat" in msgs[0].content
    assert second["message"].startswith("Sure")


def test_calls_tools_in_several_rounds_and_answers_from_the_results(world, agent):
    agent["m"] = Script(call("get_campaigns", {"params": "{}"}, "a"),
                        call("get_marketing_objectives", {"params": "{}"}, "b"),
                        "You have no campaigns or objectives yet.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "How are we doing on marketing?")
    assert body["plan_status"] == "completed", body
    assert [s.split("] ")[0] for s in body["step_summaries"]] == ["[READ", "[READ", "[RESPONSE"]
    last = agent["m"].calls[-1]
    assert [type(m).__name__ for m in last] == ["SystemMessage", "HumanMessage"]   # no invented AI turn to copy
    work = last[-1].content
    assert work.startswith("How are we doing on marketing?") and "Work done so far" in work
    assert "### get_campaigns" in work and "### get_marketing_objectives" in work   # both results, as plain text
    assert body["message"] == "You have no campaigns or objectives yet."


def test_an_action_that_needs_approval_pauses_and_resumes_after_approval(world, agent):
    args = {"name": "Brand awareness Q4", "target_metric": "reach", "target_value": 1000}
    agent["m"] = Script(call("create_marketing_objective", {"arguments_json": json.dumps(args)}),
                        "The objective was created after approval.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "Set up a brand awareness goal of 1000 reach for Q4")
    assert body["plan_status"] == "awaiting_approval", body
    assert "awaiting approval" in body["message"]
    st, objs = 200, world.client.get("/api/v1/strategy/objectives", headers=world.auth("a_admin")).json()
    assert not any(o["name"] == "Brand awareness Q4" for o in objs)        # nothing executed yet
    r = world.client.post(f"/api/v1/planning/plans/{body['plan_id']}/resume", json={"plan_id": body["plan_id"]},
                          headers=world.auth("a_admin"))
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    objs = world.client.get("/api/v1/strategy/objectives", headers=world.auth("a_admin")).json()
    assert any(o["name"] == "Brand awareness Q4" for o in objs)


def test_a_rejected_action_call_is_reported_back_and_the_model_recovers(world, agent):
    agent["m"] = Script(call("create_marketing_objective", {"arguments_json": "{}"}),
                        "I need the goal's name, metric and target to set it up.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "Create a goal")
    assert body["plan_status"] == "completed"
    work = agent["m"].calls[-1][-1].content
    assert "create_marketing_objective — FAILED" in work and "[NOT DONE" in work
    assert world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json() == []


def test_settings_tool_is_offered_to_administrators_only(world, agent):
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "hello there friend")
    assert "customize_eaawp" in agent["m"].tools
    agent["m"] = Script("Hi")
    pick(world, "a_employee", DMM)
    send(world, "a_employee", "hello there friend")
    assert "customize_eaawp" not in agent["m"].tools


def test_administrator_changes_settings_through_the_agent(world, agent):
    m = Script(call("customize_eaawp", {"arguments_json": json.dumps({"instruction": "Add Visa Assistance service"})}))
    m.customization = {"summary": "Add a service", "missing_information": [], "operations": [
        {"type": "UPDATE_COMPANY_PROFILE", "description": "Add Visa Assistance",
         "params": {"services": [{"name": "Visa Assistance", "description": "", "audience": ""}]}}]}
    agent["m"] = m
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "We now help people with visa paperwork too, please reflect that")
    assert body["plan_status"] == "awaiting_approval", body
    assert "Proposed changes (nothing has been saved yet)" in body["message"] and "Visa Assistance" in body["message"]


def test_github_data_is_shown_even_if_the_model_refuses(world, agent, monkeypatch):
    from app.integrations.providers.github_provider import GitHubProvider

    async def fake_get(self, token, path, params):
        return [{"name": "gec-website", "full_name": "gec/gec-website", "private": False, "language": "HTML",
                 "stargazers_count": 0, "open_issues_count": 0}]
    monkeypatch.setattr(GitHubProvider, "_get", fake_get)
    _connect_github(world, grants=("list_repositories",))
    pick(world, "a_admin", DMM)

    class Picks(Script):
        def bind_tools(self, tools, *a, **k):
            super().bind_tools(tools)
            gh = next(t for t in self.tools if t.endswith("list_repositories"))
            self.replies = [call(gh, {"params_json": "{}"}),
                            "Listing repositories is outside my responsibilities. Please consult the Data Analyst."]
            return self
    agent["m"] = Picks()
    body = send(world, "a_admin", "which repos do we have")
    assert "gec/gec-website" in body["message"]
    assert "outside my responsibilities" not in body["message"]


def test_a_model_failure_is_reported_not_invented(world, agent):
    agent["m"] = Script(RuntimeError("provider down"))
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "Summarise our marketing")
    assert body["plan_status"] == "failed"
    assert "AI model request failed" in body["message"]


def test_unattended_runs_still_use_the_planner(world, agent):
    from app.api.routers.execution import execute_agent
    from app.db.models import User
    from app.schemas.blueprint import AgentBlueprint, AgentExecutionRequest

    class PlannerAware(Script):
        async def ainvoke(self, messages, *a, **k):
            if "planning assistant" in str(messages[0].content):
                self.calls.append(["planner"])
                return AIMessage(content=json.dumps({"objective": "x", "steps": [
                    {"step_index": 0, "step_type": "response", "description": "Answer", "tool_name": None,
                     "arguments": {}, "depends_on": []}]}))
            return AIMessage(content="report")
    agent["m"] = PlannerAware()

    async def go():
        async with world.maker() as s:
            admin = await s.get(User, world.users["a_admin"]["id"])
            req = AgentExecutionRequest(blueprint=AgentBlueprint(agent_id="wf", role_name="Digital Marketing Manager",
                                                                 system_persona="x", tenant_id=world.tenant_a),
                                        user_prompt="Weekly report", session_id="workflow:test")
            return await execute_agent(request=req, tenant_id=world.tenant_a, db=s, user=admin)
    _run(go())
    assert ["planner"] in agent["m"].calls


def test_a_role_model_of_another_provider_does_not_break_the_chat(world, agent, monkeypatch):
    """Seen live: roles still name "gpt-4o-mini" on a Gemini-only server, and every chat failed with HTTP 500."""
    from app.llm.gateway import LLMGateway

    def unsupported(self, *a, **k):
        raise RuntimeError("model 'gpt-4o-mini' is not supported by the configured provider")
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", unsupported)
    agent["m"] = Script("Your company is GEC Services.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "what is my company name")
    assert body["message"] == "Your company is GEC Services." and body["plan_status"] == "completed"


def test_an_unexpected_agent_error_falls_back_to_the_planner(world, agent, monkeypatch):
    import app.services.chat_agent as ca

    async def broken(*a, **k):
        raise KeyError("unexpected")
    monkeypatch.setattr(ca, "run_chat_agent", broken)

    class PlannerOnly(Script):
        async def ainvoke(self, messages, *a, **k):
            if "planning assistant" in str(messages[0].content):
                return AIMessage(content=json.dumps({"objective": "x", "steps": [
                    {"step_index": 0, "step_type": "response", "description": "Answer", "tool_name": None,
                     "arguments": {}, "depends_on": []}]}))
            return AIMessage(content="Answer from the planner.")
    agent["m"] = PlannerOnly()
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "What is my CTR")
    assert body["message"] == "Answer from the planner." and body["plan_status"] == "completed"


def test_no_function_call_messages_are_replayed_to_the_model(world, agent):
    """Gemini 3 rejects a follow-up that replays its function calls without hidden signatures (seen live)."""
    agent["m"] = Script(call("get_campaigns", {"params": "{}"}), "No campaigns yet.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "How are our campaigns doing?")
    follow_up = agent["m"].calls[-1]
    assert not any(getattr(m, "tool_calls", None) for m in follow_up)
    assert not any(type(m).__name__ == "ToolMessage" for m in follow_up)


def test_if_the_follow_up_call_fails_the_answer_is_written_from_the_fetched_data(world, agent):
    class FailsAfterTool(Script):
        async def ainvoke(self, messages, *a, **k):
            self.calls.append(list(messages))
            n = len(self.calls)
            if n == 1:
                return call("get_campaigns", {"params": "{}"})
            if n == 2:
                raise RuntimeError("400 function call is missing a thought_signature")
            return AIMessage(content="From your campaign data: there are no campaigns yet.")
    agent["m"] = FailsAfterTool()
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "How are our campaigns doing?")
    assert body["plan_status"] == "completed", body
    assert body["message"] == "From your campaign data: there are no campaigns yet."
    assert "What your tools returned" in agent["m"].calls[-1][-1].content


def test_a_failed_tool_call_is_retried_with_corrected_inputs(world, agent, monkeypatch):
    """Seen live: the Search Console call failed on its inputs and the model gave up."""
    import app.core.engine as eng
    seen = []

    async def fake_exec(name, args, tools):
        seen.append(args)
        if args.get("params") == "bad":
            return "[TOOL ERROR] get_campaigns: Invalid date '3 months ago'."
        return "[]"
    monkeypatch.setattr(eng, "_execute_tool", fake_exec)
    agent["m"] = Script(call("get_campaigns", {"params": "bad"}), call("get_campaigns", {"params": "{}"}),
                        "There are no campaigns yet.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "How are our campaigns doing?")
    retry_prompt = agent["m"].calls[1][-1].content
    assert "FAILED with inputs" in retry_prompt and "call it again with corrected inputs" in retry_prompt
    assert seen == [{"params": "bad"}, {"params": "{}"}]
    assert body["message"] == "There are no campaigns yet." and body["plan_status"] == "completed"


def test_a_note_about_tools_is_never_the_answer(world, agent):
    """Seen live: the reply was "(I used these tools: integration_a143f019_get_search_analytics.)"."""
    agent["m"] = Script(call("get_campaigns", {"params": "{}"}),
                        "(I used these tools: integration_a143f019_get_search_analytics.)",
                        "You have no campaigns yet, so there is nothing to report.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "How are our campaigns doing?")
    assert body["message"] == "You have no campaigns yet, so there is nothing to report."
    assert "integration_" not in body["message"]


def test_earlier_non_answers_are_not_sent_back_as_history(world, agent):
    agent["m"] = Script("(I used these tools: integration_a143f019_get_search_analytics.)",
                        "real answer")
    pick(world, "a_admin", DMM)
    first = send(world, "a_admin", "first question")
    send(world, "a_admin", "second question", first["conversation_id"])
    assert not any("I used these tools" in str(m.content) for m in agent["m"].calls[-1])
