"""
MCP reliability: schema-aware execution, real parallel dispatch, long-running jobs.

Everything runs through the real API, grants, registry, agent loop, mcp_engine, mcp_tasks, MCP client and a REAL local
MCP server (streamable HTTP, sessions, SSE). The server's tools are modelled on the published shapes of real servers
(a scrape tool with required `objective`, a job-starting tool that returns a job `id` AND a separate `threadId`, a
status tool that takes only `id`, 404 for unknown ids). FAKED: the language model only (scripted tool calls).

Cases (see the directive's list): 1 valid call · 2 missing required · 3 invalid tool name · 4 wrong type · 5 schema
discovery · 6 schema refresh · 7 single · 8 sequential/dependent · 9 real parallel · 10 partial failure ·
11 long-running job · 12 polling timeout · 13 expired id · 14 result recovery · 15 permission rejection ·
16 duplicate prevention — plus MCP-native tasks and cancel.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.toolhub_models import McpTask
from app.toolhub import mcp_engine, mcp_tasks, mcp_tools
from tests.conftest import _run
from tests.test_chat_agent import pick, send
from tests.test_toolhub_discovery import connect, press_test_now, tool
from tests.test_toolhub_orchestration import Agent, agent, calls, executions  # noqa: F401 (fixture)
from tests.test_toolhub_security import DMM, call_tool_key, grant_tools, mcp  # noqa: F401 (fixture)

SCRAPE = {"name": "acme_scrape", "description": "Scrape one URL.", "inputSchema": {
    "type": "object", "additionalProperties": False, "required": ["url", "objective"],
    "properties": {"url": {"type": "string", "description": "Page URL"},
                   "objective": {"type": "string", "description": "Why the page is read"},
                   "formats": {"type": "array", "items": {"type": "string", "enum": ["markdown", "html"]}},
                   "maxAge": {"type": "integer", "minimum": 0}}}}
RESEARCH = {"name": "acme_research", "description": "Start web research. Returns a job id.", "inputSchema": {
    "type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string", "minLength": 1}}}}
STATUS = {"name": "acme_research_status", "description": "Status of a research job.", "inputSchema": {
    "type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}}
CANCEL = {"name": "acme_research_cancel", "description": "Cancel a research job.", "inputSchema": {
    "type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}}
PAGE = json.dumps({"markdown": "# GEC Services\nPassport, visa.", "metadata": {"statusCode": 200}})


@pytest.fixture()
def fast_jobs(monkeypatch):
    for k, v in {"mcp_task_poll_initial_s": 0.05, "mcp_task_poll_max_s": 0.1, "mcp_task_turn_wait_s": 1.5,
                 "mcp_task_max_duration_s": 60, "mcp_call_timeout_s": 2}.items():
        monkeypatch.setattr(settings, k, v)


class Jobs:
    """Server-side job store for the research tools: `ticks` status checks until done."""

    def __init__(self, ticks=2):
        self.ticks, self.jobs, self.started = ticks, {}, 0

    def start(self, args):
        self.started += 1
        jid = f"job-{self.started}"
        self.jobs[jid] = 0
        return json.dumps({"success": True, "id": jid, "threadId": f"thread-{self.started}"})

    def status(self, args):
        jid = args.get("id")
        if jid not in self.jobs:
            return json.dumps({"error": f"Job {jid} not found (404)"}), True
        self.jobs[jid] += 1
        if self.jobs[jid] < self.ticks:
            return json.dumps({"status": "processing", "progress": self.jobs[jid]})
        return json.dumps({"status": "completed", "data": {"answer": "GEC Services offers passport services"}})


def server(world, agent, mcp, tools=(SCRAPE, RESEARCH, STATUS, CANCEL), grant=None, jobs=None):
    s = mcp(list(tools))
    s.outputs["acme_scrape"] = PAGE
    if jobs:
        s.outputs["acme_research"] = jobs.start
        s.outputs["acme_research_status"] = jobs.status
    iid = connect(world, s.url, "Acme")
    assert press_test_now(world, iid)["success"]
    grant_tools(world, iid, *(grant if grant is not None else [t["name"] for t in tools]))
    pick(world, "a_admin", DMM)
    agent["m"] = Agent("hi")
    send(world, "a_admin", "hello there friend")
    return s, iid, call_tool_key(agent["m"])


def work_of(agent) -> str:
    return agent["m"].calls[-1][-1].content


def tasks(world) -> list[McpTask]:
    async def go():
        async with world.maker() as db:
            return list((await db.execute(select(McpTask).where(McpTask.tenant_id == world.tenant_a)
                                          .order_by(McpTask.created_at))).scalars())
    return _run(go())


def sent(s, name=None):
    return [c for c in s.calls if name is None or c["name"] == name]


# 1, 7 ─ valid single call
def test_1_7_a_valid_call_is_dispatched_with_exactly_its_arguments(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    args = {"url": "https://gecservices.in", "objective": "list the services", "formats": ["markdown"]}
    agent["m"] = Agent(calls((k + "acme_scrape", args)), "GEC Services offers passport and visa help.")
    body = send(world, "a_admin", "Use Acme to scrape https://gecservices.in")
    assert sent(s) == [{"name": "acme_scrape", "arguments": args}]
    assert '"statusCode": 200' in work_of(agent) and body["plan_status"] == "completed"
    assert [t["name"] for t in body["tool_calls"]] == [k + "acme_scrape"]


# 2, 4 ─ missing required / wrong type / unexpected argument: nothing sent, model told exactly what to fix
@pytest.mark.parametrize("args,problem", [
    ({"url": "https://gecservices.in"}, "objective is missing (required)"),
    ({"url": 42, "objective": "x"}, "url should be string, got int"),
    ({"url": "u", "objective": "x", "formats": ["pdf"]}, "formats[0] must be one of markdown, html"),
    ({"url": "u", "objective": "x", "maxAge": -5}, "maxAge must be ≥ 0"),
    ({"url": "u", "objective": "x", "link": "y"}, "link is not an input of this tool"),
])
def test_2_4_invalid_arguments_are_never_dispatched(world, agent, mcp, args, problem):
    s, iid, k = server(world, agent, mcp)
    agent["m"] = Agent(calls((k + "acme_scrape", args)), "Need valid inputs.")
    send(world, "a_admin", "Use Acme to scrape it")
    assert sent(s) == []
    w = work_of(agent)
    assert problem in w and "Nothing was sent to the server" in w and "objective (string, REQUIRED)" in w
    rec = [r for r in executions(world) if r.tool_key == k + "acme_scrape"][-1]
    assert rec.status == "failed" and rec.error_category == "invalid_args"


def test_2_the_model_corrects_its_arguments_within_a_bounded_number_of_retries(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    bad = calls((k + "acme_scrape", {"url": "https://gecservices.in"}))
    good = calls((k + "acme_scrape", {"url": "https://gecservices.in", "objective": "services"}))
    agent["m"] = Agent(bad, good, "Done.")
    send(world, "a_admin", "Use Acme to scrape https://gecservices.in")
    assert len(sent(s)) == 1                                     # corrected call went through once
    agent["m"] = Agent(bad, bad, bad, "I need the objective.")
    send(world, "a_admin", "Use Acme to scrape https://gecservices.in")
    assert len(sent(s)) == 1                                     # still one: three bad calls, none dispatched
    assert f"rejected {mcp_engine.MAX_CORRECTIONS} times" in work_of(agent)


# 3 ─ invalid tool names are rejected before anything
@pytest.mark.parametrize("name", [None, "", "null", "undefined", "None", "a b", "x" * 200, 42])
def test_3_invalid_tool_names_are_rejected_before_execution(world, agent, mcp, name):
    s, iid, k = server(world, agent, mcp)

    async def go():
        async with world.maker() as db:
            return await mcp_engine.run(db, world.tenant_a, DMM, None, iid, name, {"url": "u", "objective": "o"})
    out = _run(go())
    assert out.startswith("[VALIDATION ERROR]") and "missing or invalid" in out and sent(s) == []


def test_3_a_tool_the_server_does_not_have_is_refused_and_the_registry_refreshed(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    agent["m"] = Agent(calls((k + "acme_nonexistent", {})), "No such tool.")
    send(world, "a_admin", "Use Acme's nonexistent tool")
    assert sent(s) == [] and "is not one of your tools" in work_of(agent)

    async def go():
        async with world.maker() as db:
            return await mcp_engine.run(db, world.tenant_a, DMM, None, iid, "acme_nonexistent", {})
    assert _run(go()).startswith("[PERMISSION DENIED]")              # grants are checked first
    grant_tools(world, iid, "acme_nonexistent")                     # even granted, a tool the server lacks…
    assert "not in the registry" in _run(go()) and sent(s) == []    # …is refused before anything is sent


# 5 ─ discovery: each granted tool is a native function with its real schema
def test_5_granted_tools_are_offered_as_native_functions_with_their_schemas(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    assert {k + "acme_scrape", k + "acme_research", k + "acme_research_status", "check_task"} <= set(agent["m"].tools)
    assert not any(t.endswith("_call_tool") for t in agent["m"].tools)          # no JSON-string adapter anymore

    async def go():
        async with world.maker() as db:
            return await mcp_tools.native_tools(db, world.tenant_a, DMM, "p")
    t = _run(go())[k + "acme_scrape"]
    schema = t.args_schema
    assert schema["required"] == ["url", "objective"]
    assert schema["properties"]["formats"]["items"]["enum"] == ["markdown", "html"]
    assert "objective (string, REQUIRED)" in t.description and "maxAge (integer, optional)" in t.description
    assert t.metadata["mcp_tool"] == "acme_scrape" and "server_url" not in json.dumps(t.metadata)


# 6 ─ schema refresh
def test_6_a_changed_server_schema_is_picked_up_and_enforced(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    s.tools[0] = {**SCRAPE, "inputSchema": {**SCRAPE["inputSchema"],
                                            "required": ["url", "objective", "country"],
                                            "properties": {**SCRAPE["inputSchema"]["properties"],
                                                           "country": {"type": "string"}}}}
    # Not refreshed yet: the live schema check in the dispatcher still stops the call.
    agent["m"] = Agent(calls((k + "acme_scrape", {"url": "u", "objective": "o"})), "Needs country.")
    send(world, "a_admin", "Use Acme to scrape it")
    assert sent(s) == [] and "country is missing (required)" in work_of(agent)
    press_test_now(world, iid)                                                 # registry refresh

    async def go():
        async with world.maker() as db:
            return await mcp_tools.native_tools(db, world.tenant_a, DMM, "p")
    assert "country" in _run(go())[k + "acme_scrape"].args_schema["required"]


# 8 ─ sequential, dependent calls
def test_8_dependent_calls_run_in_order_with_the_first_result_passed_on(world, agent, mcp, fast_jobs):
    s, iid, k = server(world, agent, mcp)
    agent["m"] = Agent(calls((k + "acme_scrape", {"url": "https://gecservices.in", "objective": "find the title"})),
                       calls((k + "acme_scrape", {"url": "https://gecservices.in/services", "objective":
                                                  "follow up on GEC Services"})), "Both pages read.")
    send(world, "a_admin", "Use Acme to scrape gecservices.in then its services page")
    assert [c["arguments"]["url"] for c in sent(s)] == ["https://gecservices.in", "https://gecservices.in/services"]
    assert "GEC Services" in agent["m"].calls[1][-1].content                   # 2nd step saw the 1st result


# 9 ─ real parallel execution
def test_9_independent_mcp_calls_really_run_at_the_same_time(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    s.delays["acme_scrape"] = 0.7
    urls = ["https://a.example", "https://b.example", "https://c.example"]
    agent["m"] = Agent(calls(*((k + "acme_scrape", {"url": u, "objective": "compare"}) for u in urls)), "Compared.")
    t0 = time.monotonic()
    send(world, "a_admin", "Use Acme to scrape these three sites " + " ".join(urls))
    took = time.monotonic() - t0
    assert sorted(c["arguments"]["url"] for c in sent(s)) == urls
    assert took < 1.9, f"3 × 0.7 s calls took {took:.2f}s — not parallel"
    recs = [r for r in executions(world) if r.tool_key == k + "acme_scrape"]
    assert len(recs) == 3 and all(r.recovery == "ran in parallel" and r.status == "success" for r in recs)


# 10 ─ partial failure
def test_10_one_failing_call_does_not_lose_the_others(world, agent, mcp):
    s, iid, k = server(world, agent, mcp)
    s.outputs["acme_scrape"] = lambda a: ("upstream 500", True) if "b." in a["url"] else PAGE
    agent["m"] = Agent(calls((k + "acme_scrape", {"url": "https://a.example", "objective": "x"}),
                             (k + "acme_scrape", {"url": "https://b.example", "objective": "x"}),
                             (k + "acme_scrape", {"url": "https://c.example"})), "Two of three worked.")
    body = send(world, "a_admin", "Use Acme to scrape a, b and c")
    w = work_of(agent)
    assert body["plan_status"] == "completed"
    assert w.count('"statusCode": 200') == 1 + 0 or w.count("GEC Services") >= 1
    assert "TOOL ERROR" in w and "upstream 500" in w                          # b: the server's own failure
    assert "objective is missing (required)" in w                             # c: never sent
    assert sorted(c["arguments"]["url"] for c in sent(s)) == ["https://a.example", "https://b.example"]


# 11 ─ long-running job: recognised, the right id polled, result returned
def test_11_a_job_is_followed_with_its_job_id_not_its_thread_id(world, agent, mcp, fast_jobs):
    jobs = Jobs(ticks=2)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "What does GEC Services offer?"})), "Found it.")
    send(world, "a_admin", "Use Acme to research GEC Services")
    polls = sent(s, "acme_research_status")
    assert polls and all(p["arguments"] == {"id": "job-1"} for p in polls)   # never "thread-1"
    t = tasks(world)[-1]
    assert (t.state, t.remote_id, t.remote_id_field, t.status_tool) == ("COMPLETED", "job-1", "id",
                                                                       "acme_research_status")
    assert "passport services" in t.result_text and "[TASK COMPLETED]" in work_of(agent)


# 12 ─ polling timeout: a failed status check is not a failed job, and nothing is restarted
def test_12_status_check_timeouts_are_polling_failures_then_the_job_times_out(world, agent, mcp, fast_jobs,
                                                                              monkeypatch):
    jobs = Jobs(ticks=99)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    monkeypatch.setattr(settings, "mcp_call_timeout_s", 1)
    s.delays["acme_research_status"] = 1.5
    monkeypatch.setattr(settings, "mcp_task_turn_wait_s", 2.5)
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "slow"})), "It is still running.")
    send(world, "a_admin", "Use Acme to research something slow")
    t = tasks(world)[-1]
    assert t.state == "RUNNING" and t.poll_failures >= 1 and "did not respond" in t.last_poll_error
    assert "[TASK RUNNING]" in work_of(agent) and jobs.started == 1           # not restarted
    rec = [r for r in executions(world) if r.tool_key == k + "acme_research"][-1]
    assert rec.retries == 0 and rec.status == "success"                     # starting the job succeeded

    async def expire_deadline():
        async with world.maker() as db:
            row = (await db.execute(select(McpTask).where(McpTask.id == t.id))).scalar_one()
            from datetime import datetime, timedelta, timezone
            row.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await mcp_tasks.poll_once(db, row)
            await db.commit()
            return row.state
    before = len(sent(s, "acme_research_status"))
    assert _run(expire_deadline()) == "TIMED_OUT"
    assert len(sent(s, "acme_research_status")) == before                     # no further status call


# 13 ─ expired / unknown id: never polled again
def test_13_an_unknown_job_id_is_expired_and_never_polled_again(world, agent, mcp, fast_jobs):
    jobs = Jobs(ticks=99)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    jobs.status = lambda a: (json.dumps({"error": "Job not found (404)"}), True)
    s.outputs["acme_research_status"] = jobs.status
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "x"})), "The job is gone.")
    send(world, "a_admin", "Use Acme to research x")
    t = tasks(world)[-1]
    assert t.state == "EXPIRED" and "404" in t.error
    n = len(sent(s, "acme_research_status"))
    assert n == 1

    async def again():
        async with world.maker() as db:
            row = (await db.execute(select(McpTask).where(McpTask.id == t.id))).scalar_one()
            await mcp_tasks.poll_once(db, row)
            await mcp_tasks.poll_due(world.maker)
    _run(again())
    assert len(sent(s, "acme_research_status")) == n
    assert "[TASK EXPIRED]" in work_of(agent)
    rec = [r for r in executions(world) if r.tool_key == k + "acme_research"][-1]
    assert rec.error_category == "task_expired" and rec.retries == 0 and jobs.started == 1


# 14 ─ result recovery after the answer (and after a restart: a new session, the background poller)
def test_14_a_job_finishing_later_is_recovered_by_the_poller_and_check_task(world, agent, mcp, fast_jobs, monkeypatch):
    jobs = Jobs(ticks=4)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    monkeypatch.setattr(settings, "mcp_task_turn_wait_s", 0.0)
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "later"})), "Started; it runs in the background.")
    send(world, "a_admin", "Use Acme to research later")
    t = tasks(world)[-1]
    assert t.state == "RUNNING"

    async def background():
        for _ in range(20):
            await mcp_tasks.poll_due(world.maker)          # what the poller does each round, in fresh sessions
            async with world.maker() as db:
                row = (await db.execute(select(McpTask).where(McpTask.id == t.id))).scalar_one()
                if row.state in mcp_tasks.TERMINAL:
                    return row.state
            await asyncio.sleep(0.12)
    assert _run(background()) == "COMPLETED"
    agent["m"] = Agent(calls(("check_task", {"task_id": t.id})), "Here is the result.")
    send(world, "a_admin", "Is the research done?")
    assert "[TASK COMPLETED]" in work_of(agent) and "passport services" in work_of(agent)
    d = world.client.get(f"/api/v1/toolhub/tasks/{t.id}", headers=world.auth("a_admin")).json()
    assert d["state"] == "COMPLETED" and "passport services" in d["result_text"]
    assert world.client.get(f"/api/v1/toolhub/tasks/{t.id}", headers=world.auth("b_admin")).status_code == 404


# 15 ─ permission rejection
def test_15_ungranted_tools_are_not_offered_and_are_refused_by_the_engine(world, agent, mcp):
    s, iid, k = server(world, agent, mcp, grant=["acme_scrape"])
    assert k + "acme_research" not in agent["m"].tools

    async def go():
        async with world.maker() as db:
            return await mcp_engine.run(db, world.tenant_a, DMM, None, iid, "acme_research", {"prompt": "x"})
    out = _run(go())
    assert out.startswith("[PERMISSION DENIED]") and sent(s) == []

    async def other_company():
        async with world.maker() as db:
            return await mcp_engine.run(db, world.tenant_b, DMM, None, iid, "acme_scrape",
                                        {"url": "u", "objective": "o"})
    assert _run(other_company()).startswith("[PERMISSION DENIED]") and sent(s) == []


def test_15_a_job_whose_status_tool_is_not_granted_is_not_polled(world, agent, mcp, fast_jobs):
    jobs = Jobs(ticks=1)
    s, iid, k = server(world, agent, mcp, grant=["acme_research"], jobs=jobs)
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "x"})), "Running.")
    send(world, "a_admin", "Use Acme to research x")
    t = tasks(world)[-1]
    assert t.state == "RUNNING" and "not been granted the status tool" in t.last_poll_error
    assert sent(s, "acme_research_status") == []


# 16 ─ duplicate prevention
def test_16_the_same_job_is_not_started_twice(world, agent, mcp, fast_jobs, monkeypatch):
    jobs = Jobs(ticks=99)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    monkeypatch.setattr(settings, "mcp_task_turn_wait_s", 0.2)
    call = calls((k + "acme_research", {"prompt": "same question"}))
    agent["m"] = Agent(call, "Started.")
    send(world, "a_admin", "Use Acme to research the same question")
    agent["m"] = Agent(call, "Already running.")
    send(world, "a_admin", "Use Acme to research the same question")
    assert jobs.started == 1 and len(sent(s, "acme_research")) == 1
    assert "[DUPLICATE PREVENTED]" in work_of(agent) and len(tasks(world)) == 1


# Extra: MCP-native tasks (tasks/get, tasks/result) and cancel
def test_mcp_native_tasks_are_followed_with_tasks_get_and_result(world, agent, mcp, fast_jobs):
    s, iid, k = server(world, agent, mcp, tools=(SCRAPE,))
    s.outputs["acme_scrape"] = json.dumps({"task": {"taskId": "T-9", "status": "working", "pollInterval": 50}})
    state = {"n": 0}

    def get(p):
        state["n"] += 1
        return {"taskId": p["taskId"], "status": "completed" if state["n"] >= 2 else "working"}
    s.methods["tasks/get"] = get
    s.methods["tasks/result"] = lambda p: {"content": [{"type": "text", "text": "native task result"}]}
    agent["m"] = Agent(calls((k + "acme_scrape", {"url": "u", "objective": "o"})), "Done.")
    send(world, "a_admin", "Use Acme to scrape u")
    t = tasks(world)[-1]
    assert (t.mechanism, t.state, t.result_text) == ("mcp_tasks", "COMPLETED", "native task result")


def test_a_running_job_can_be_cancelled_through_the_servers_cancel_tool(world, agent, mcp, fast_jobs, monkeypatch):
    jobs = Jobs(ticks=99)
    s, iid, k = server(world, agent, mcp, jobs=jobs)
    s.outputs["acme_research_cancel"] = json.dumps({"success": True})
    monkeypatch.setattr(settings, "mcp_task_turn_wait_s", 0.1)
    agent["m"] = Agent(calls((k + "acme_research", {"prompt": "x"})), "Running.")
    send(world, "a_admin", "Use Acme to research x")
    t = tasks(world)[-1]
    assert world.client.post(f"/api/v1/toolhub/tasks/{t.id}/cancel", headers=world.auth("a_employee")).status_code == 403
    r = world.client.post(f"/api/v1/toolhub/tasks/{t.id}/cancel", headers=world.auth("a_admin"))
    assert r.status_code == 200 and r.json()["state"] == "CANCELLED"
    assert sent(s, "acme_research_cancel") == [{"name": "acme_research_cancel", "arguments": {"id": "job-1"}}]
    assert world.client.get("/api/v1/toolhub/tasks", headers=world.auth("a_admin")).json()["tasks"][0]["state"] == \
        "CANCELLED"
