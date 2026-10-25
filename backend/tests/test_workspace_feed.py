"""Activity / Tasks / Insights come from real records, scoped to the selected AI employee and to the person.

FAKED: the language model and GitHub's HTTP API."""
from __future__ import annotations

from tests.test_role_intelligence import (  # noqa: F401  (fixtures)
    _connect_github, _propose_objective, ask, model, objective_model, pick,
)

F = "/api/v1/workspace/feed"
DMM = "DIGITAL_MARKETING_MANAGER"


def feed(w, who, kind):
    r = w.client.get(f"{F}/{kind}", headers=w.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_nothing_is_shown_before_a_role_is_selected(world):
    for kind in ("activity", "tasks", "insights"):
        assert feed(world, "a_employee", kind) == {"role_key": None, "items": []}
    assert world.client.get(f"{F}/bogus", headers=world.auth("a_employee")).status_code == 404


def test_activity_lists_real_runs_and_employees_see_only_their_own(world, model):
    pick(world, "a_employee", DMM)
    pick(world, "a_admin", DMM)
    ask(world, "a_employee", "Prepare a monthly marketing report", DMM)
    ask(world, "a_admin", "Summarise our brand positioning", DMM)
    mine = feed(world, "a_employee", "activity")
    assert mine["scope"] == "mine" and [i["title"] for i in mine["items"]] == ["Prepare a monthly marketing report"]
    assert mine["items"][0]["status"] == "completed" and "a_employee" in mine["items"][0]["detail"]
    company = feed(world, "a_admin", "activity")
    assert company["scope"] == "company" and len(company["items"]) == 2
    pick(world, "a_employee", "MEDICAL_ASSISTANT")
    assert feed(world, "a_employee", "activity")["items"] == []           # another AI employee's runs are not mixed in


def test_tasks_show_the_real_pending_approval(world, objective_model):
    _propose_objective(world)
    items = feed(world, "a_admin", "tasks")["items"]
    assert [(i["kind"], i["status"]) for i in items] == [("approval", "awaiting_approval")]
    assert "create marketing objective" in items[0]["title"]


def test_tasks_show_saved_setup_requests_to_their_owner(world, model):
    pick(world, "a_employee", DMM)
    ask(world, "a_employee", "Show me our Google Analytics traffic for last week", DMM)
    items = feed(world, "a_employee", "tasks")["items"]
    assert [i["kind"] for i in items] == ["setup"]


def test_insights_only_include_answers_built_on_data_a_tool_read(world, monkeypatch):
    import json
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from app.integrations.providers.github_provider import GitHubProvider
    from app.llm.gateway import LLMGateway
    from tests.test_role_intelligence import Recorder

    async def fake_get(self, token, path, params):
        return [{"name": "site", "full_name": "gec/site", "private": False, "language": "HTML",
                 "stargazers_count": 0, "open_issues_count": 0}]
    monkeypatch.setattr(GitHubProvider, "_get", fake_get)

    class Planner(Recorder):
        async def ainvoke(self, messages, *a, **k):
            system, human = str(messages[0].content), str(messages[-1].content)
            if "planning assistant" in system and "repositories" in human.rsplit("User request:", 1)[-1]:
                tool = next(t.strip().split()[1] for t in human.splitlines() if "list_repositories" in t)
                return AIMessage(content=json.dumps({"objective": "list repos", "steps": [
                    {"step_index": 0, "step_type": "read", "description": "List", "tool_name": tool, "arguments": {}, "depends_on": []},
                    {"step_index": 1, "step_type": "response", "description": "Answer", "tool_name": None, "arguments": {}, "depends_on": [0]}]}))
            return await super().ainvoke(messages, *a, **k)
    rec = Planner()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: rec)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    pick(world, "a_admin", DMM)
    _connect_github(world, grants=("list_repositories",))
    ask(world, "a_admin", "List repositories accessible", DMM)
    ask(world, "a_admin", "Write a friendly greeting for our newsletter", DMM)   # no data read -> not an insight
    items = feed(world, "a_admin", "insights")["items"]
    assert len(items) == 1 and items[0]["sources"] == ["Integration: list repositories"]
    assert items[0]["detail"]
