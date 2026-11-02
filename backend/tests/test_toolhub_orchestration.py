"""
Suites B (orchestration), E (diagnostics & recovery), F (AI employee integration) and G (visualization), through the
REAL chat agent, API, governance, sandbox, registry and database.

FAKED: the language model (a script of replies with native tool calls) and the internet functions behind web_search /
read_web_page (so no external site is contacted). Everything they feed into is real.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.db.toolhub_models import McpDiscoverySnapshot, ToolExecution
from tests.conftest import _run
from tests.test_chat_agent import Script, call, pick, send
from tests.test_toolhub_builder import spec as tool_spec

DMM, MED, ANALYST = "DIGITAL_MARKETING_MANAGER", "MEDICAL_ASSISTANT", "DATA_INTELLIGENCE_ANALYST"


def calls(*pairs):
    """One model turn calling several tools at once: calls(("name", {args}), ...)."""
    return AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"c{i}"} for i, (n, a) in enumerate(pairs)])


class Agent(Script):
    """Script + Tool Builder spec replies."""

    def __init__(self, *replies, specs=()):
        super().__init__(*replies)
        self.specs = list(specs)

    async def ainvoke(self, messages, *a, **k):
        if "reusable Python tools" in str(messages[0].content):
            return AIMessage(content=json.dumps(self.specs.pop(0) if self.specs else tool_spec()))
        return await super().ainvoke(messages, *a, **k)


@pytest.fixture()
def agent(monkeypatch):
    from types import SimpleNamespace
    import app.config as cfg
    from app.llm.gateway import LLMGateway
    cfg.settings.__dict__["chat_engine"] = "agent"
    holder = {"m": Agent("ok")}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


@pytest.fixture()
def web(monkeypatch):
    """The internet behind web_search/read_web_page, scripted per query/url (with optional delay and failures)."""
    import app.tools.web_tools as wt
    st = {"delay": 0.0, "fail": {}, "calls": [], "pages": {}}

    async def search(query):
        st["calls"].append(("search", query))
        await asyncio.sleep(st["delay"])
        n = st["fail"].get(query, 0)
        if n:
            st["fail"][query] = n - 1
            return "[TIMEOUT] web_search: timed out" if n != 99 else "[TOOL ERROR] web_search: invalid_grant expired"
        return f"Results for {query}: GEC Services Kochi; Source: Google Search (web)"

    async def page(url):
        st["calls"].append(("page", url))
        await asyncio.sleep(st["delay"])
        return st["pages"].get(url, f"Page: {url}\nServices: Passport, Visa\nSource: {url}")
    monkeypatch.setattr(wt, "search_the_web", search)
    monkeypatch.setattr(wt, "fetch_page", page)
    return st


NAMES = {DMM: "Digital Marketing Manager", MED: "Medical Assistant", ANALYST: "Data Analyst"}


def send_as(world, role, prompt):
    body = {"blueprint": {"agent_id": "cabin", "role_name": NAMES[role], "role_key": role, "system_persona": "x",
                          "allowed_tools": [], "guarded_tools": [], "tenant_id": world.users["a_admin"]["tenant_id"]},
            "user_prompt": prompt}
    r = world.client.post("/api/v1/agent/execute", json=body, headers=world.auth("a_admin"))
    assert r.status_code == 200, r.text
    return r.json()


def executions(world):
    async def go():
        async with world.maker() as s:
            return list((await s.execute(select(ToolExecution).where(ToolExecution.tenant_id == world.tenant_a)
                                         .order_by(ToolExecution.started_at))).scalars())
    return _run(go())


# ── Suite B — orchestration ──────────────────────────────────────────────────

def test_independent_calls_in_one_turn_run_in_parallel(world, agent, web):
    web["delay"] = 0.6
    agent["m"] = Agent(calls(("web_search", {"query": "passport agencies Kochi"}),
                             ("web_search", {"query": "visa services Kochi"}),
                             ("read_web_page", {"url": "https://gecservices.in"})),
                       "Here is the comparison.")
    pick(world, "a_admin", DMM)
    t0 = time.monotonic()
    body = send(world, "a_admin", "Compare us with competitors in Kochi")
    took = time.monotonic() - t0
    assert body["plan_status"] == "completed" and body["message"] == "Here is the comparison."
    assert took < 1.5, f"three 0.6 s calls took {took:.1f}s — not parallel"
    work = agent["m"].calls[-1][-1].content
    assert "passport agencies Kochi" in work and "visa services Kochi" in work and "gecservices.in" in work
    rows = executions(world)
    assert len(rows) == 3 and all(r.status == "success" and r.recovery == "ran in parallel" for r in rows)


def test_a_tool_is_built_mid_chat_then_used_on_earlier_results_and_charted(world, agent, web):
    rows = [{"page": "/passport", "clicks": 30, "impressions": 1200}, {"page": "/visa", "clicks": 12, "impressions": 800}]
    web["pages"]["https://gecservices.in/stats"] = "Page stats\n" + json.dumps(rows) + "\nSource: gecservices.in"
    agent["m"] = Agent(
        calls(("read_web_page", {"url": "https://gecservices.in/stats"})),
        calls(("find_tools", {"need": "click-through rate per landing page"})),
        calls(("build_tool", {"capability": "calculate click-through rate per landing page",
                              "details": "rows of page, clicks, impressions"})),
        calls(("gen_page_ctr_calculator", {"rows": rows})),
        calls(("make_chart", {"chart_json": json.dumps({"title": "CTR by page", "unit": "%", "labels": ["/passport", "/visa"],
                                                         "series": [{"name": "CTR", "values": [2.5, 1.5]}]})})),
        "Passport has the better CTR (2.5% vs 1.5%).")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "Which landing page has the better click-through rate? Show a chart.")
    assert body["plan_status"] == "completed", body
    assert [s.split("] ")[0] for s in body["step_summaries"]] == ["[READ"] * 5 + ["[RESPONSE"]
    work = agent["m"].calls[-1][-1].content
    assert "is validated (2 tests passed in the sandbox)" in work and '"ctr": 2.5' in work and '"ctr": 1.5' in work
    assert body["charts"] and body["charts"][0]["title"] == "CTR by page" and body["charts"][0]["type"] == "bar"
    saved = world.client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=world.auth("a_admin")).json()
    assert saved["messages"][-1]["charts"][0]["series"][0]["values"] == [2.5, 1.5]   # reopened report keeps it


def test_a_failing_tool_leads_to_another_route_not_an_invented_answer(world, agent, web):
    web["fail"]["competitors Kochi"] = 99                          # non-transient (auth) failure
    agent["m"] = Agent(calls(("web_search", {"query": "competitors Kochi"})),
                       calls(("read_web_page", {"url": "https://competitor.example"})),
                       "From the competitor's page: they offer passport services.")
    pick(world, "a_admin", DMM)
    body = send(world, "a_admin", "What do competitors in Kochi offer?")
    second = agent["m"].calls[1][-1].content
    assert "web_search — FAILED" in second and "[WHAT IS NEEDED]" in second
    assert body["message"].startswith("From the competitor's page")


# ── Suite E — diagnostics and recovery ───────────────────────────────────────

def test_transient_failures_are_retried_with_backoff_and_recorded(world, agent, web):
    web["fail"]["gec reviews"] = 2
    agent["m"] = Agent(calls(("web_search", {"query": "gec reviews"})), "Found reviews.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "Find reviews of GEC")
    rec = executions(world)[-1]
    assert rec.status == "success" and rec.retries == 2 and "retry 2 after timeout" in rec.recovery
    assert [c for c in web["calls"] if c[0] == "search"] == [("search", "gec reviews")] * 3


def test_retries_are_bounded_and_the_failure_is_reported(world, agent, web):
    web["fail"]["slow query"] = 5
    agent["m"] = Agent(calls(("web_search", {"query": "slow query"})), "The search timed out.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "search slow query")
    rec = executions(world)[-1]
    assert rec.status == "failed" and rec.error_category == "timeout" and rec.retries == 2
    assert len(web["calls"]) == 3                                         # 1 + 2 retries, then stop


def test_auth_failures_are_not_retried_and_say_what_is_needed(world, agent, web):
    web["fail"]["q"] = 99
    agent["m"] = Agent(calls(("web_search", {"query": "q"})), "I could not search.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "search q")
    rec = executions(world)[-1]
    assert rec.error_category == "auth" and rec.retries == 0 and len(web["calls"]) == 1
    assert "reconnect" in agent["m"].calls[-1][-1].content


def test_invalid_arguments_to_a_generated_tool_are_not_retried(world, agent):
    agent["m"] = Agent(calls(("build_tool", {"capability": "calculate click-through rate per landing page"})),
                       calls(("gen_page_ctr_calculator", {"rows": [{"page": "/a"}]})),
                       "The rows were missing clicks.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "work out CTR")
    gen = [r for r in executions(world) if r.tool_key == "gen_page_ctr_calculator"]
    assert len(gen) == 1 and gen[0].error_category == "invalid_args" and gen[0].retries == 0


def test_actions_that_change_things_are_never_retried(world, agent):
    agent["m"] = Agent(calls(("create_marketing_objective", {"arguments_json": "{}"})), "Missing details.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "create an objective")
    acts = [r for r in executions(world) if r.tool_source == "action"]
    assert len(acts) == 1 and acts[0].status == "blocked" and acts[0].retries == 0


# ── Suite F — AI employee integration ────────────────────────────────────────

def test_roles_get_only_their_tools(world, agent):
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "hello there friend")
    assert {"find_tools", "build_tool", "make_chart", "web_search"} <= set(agent["m"].tools)
    agent["m"] = Agent("hi")
    pick(world, "a_admin", MED)
    send_as(world, MED, "hello there friend")
    tools = set(agent["m"].tools)
    assert "find_tools" in tools and "make_chart" in tools
    assert "build_tool" not in tools and "web_search" not in tools          # medical: approved workflows only


def test_a_tool_built_by_one_employee_is_not_offered_to_another_until_granted(world, agent):
    agent["m"] = Agent(calls(("build_tool", {"capability": "calculate click-through rate per landing page"})), "Built.")
    pick(world, "a_admin", DMM)
    send(world, "a_admin", "build a CTR calculator")
    agent["m"] = Agent(calls(("find_tools", {"need": "click-through rate per landing page"})), "It exists.")
    pick(world, "a_admin", ANALYST)
    send_as(world, ANALYST, "is there a CTR calculator?")
    assert "gen_page_ctr_calculator" not in agent["m"].tools
    found = agent["m"].calls[-1][-1].content
    assert "gen_page_ctr_calculator" in found and "NOT granted to you" in found
    tool_id = world.client.get("/api/v1/toolhub/registry", headers=world.auth("a_admin")).json()["tools"][0]["id"]
    assert world.client.post(f"/api/v1/toolhub/tools/{tool_id}/grant", json={"role_key": ANALYST},
                             headers=world.auth("a_admin")).json() == {"ok": True}
    agent["m"] = Agent("ok")
    send_as(world, ANALYST, "hello there friend")
    assert "gen_page_ctr_calculator" in agent["m"].tools


# ── Suite G — visualization ──────────────────────────────────────────────────

def _chart_turn(world, agent, web, chart, data):
    web["pages"]["https://x.example/d"] = "Data\n" + json.dumps(data) + "\nSource: x.example"
    agent["m"] = Agent(calls(("read_web_page", {"url": "https://x.example/d"})),
                       calls(("make_chart", {"chart_json": json.dumps(chart)})), "Done.")
    pick(world, "a_admin", DMM)
    return send(world, "a_admin", "chart it"), agent["m"].calls[-1][-1].content


DAILY = [{"date": f"2026-10-{d:02d}", "clicks": 10 + d} for d in range(1, 15)]


@pytest.mark.parametrize("chart, expected_type", [
    ({"title": "Daily clicks", "labels": [r["date"] for r in DAILY],
      "series": [{"name": "Clicks", "values": [r["clicks"] for r in DAILY]}], "y_label": "clicks"}, "line"),
    ({"title": "KPIs", "kpis": [{"label": "Total clicks", "value": sum(r["clicks"] for r in DAILY)}]}, "kpi"),
    ({"title": "Pie", "type": "pie", "labels": ["2026-10-01", "2026-10-02"], "series": [{"name": "Clicks", "values": [11, 12]}]}, "pie"),
])
def test_chart_types_are_chosen_from_the_data(world, agent, web, chart, expected_type):
    body, _ = _chart_turn(world, agent, web, chart, DAILY)
    assert body["charts"][0]["type"] == expected_type


def test_invented_chart_values_are_refused_and_the_answer_still_arrives(world, agent, web):
    chart = {"title": "Fake", "labels": ["a", "b"], "series": [{"name": "Clicks", "values": [9999, 1234]}]}
    body, work = _chart_turn(world, agent, web, chart, DAILY)
    assert body["charts"] == [] and body["message"] == "Done."
    assert "not in the data your tools returned: 9999, 1234" in work


def test_charts_need_data_and_matching_shapes(world, agent, web):
    body, work = _chart_turn(world, agent, web, {"title": "Empty", "labels": ["a"], "series": []}, DAILY)
    assert body["charts"] == [] and "needs at least one series" in work


def test_a_large_dataset_charts_within_limits(world, agent, web):
    big = [{"day": i, "clicks": 1000 + i} for i in range(200)]
    chart = {"title": "200 points", "labels": [str(r["day"]) for r in big],
             "series": [{"name": "Clicks", "values": [r["clicks"] for r in big]}]}
    body, _ = _chart_turn(world, agent, web, chart, big)
    assert len(body["charts"][0]["labels"]) == 200
