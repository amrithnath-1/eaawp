"""
LIVE check (skipped unless configured): the reported request, end to end through EAAWP's real router, grants, agent
loop and MCP dispatcher, against a REAL MCP server such as Firecrawl.

    EAAWP_LIVE_MCP_URL="https://mcp.firecrawl.dev/<your key>/v2/mcp" pytest tests/test_live_mcp_scrape.py -s

The URL (it may carry a key) is read from the environment only: it is never printed, stored in the repository or
written to the test output. The language model is scripted to make the one scrape call, so what is verified is the
routing, permission check, argument validation and the real dispatch — and what the server really returned.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.test_chat_agent import pick, send
from tests.test_toolhub_discovery import connect, press_test_now
from tests.test_toolhub_orchestration import agent, calls  # noqa: F401 (fixture)
from tests.test_toolhub_security import DMM, call_tool_key, grant_tools
from tests.test_mcp_routing_and_security import Model, REPORTED

URL = os.environ.get("EAAWP_LIVE_MCP_URL", "")
TARGET = os.environ.get("EAAWP_LIVE_SCRAPE_TARGET", "https://gecservices.in")

pytestmark = pytest.mark.skipif(not URL, reason="EAAWP_LIVE_MCP_URL not set: live MCP execution not verified here")


def test_live_reported_request_scrapes_through_eaawps_dispatcher(world, agent):
    iid = connect(world, URL, "Firecrawl")
    tested = press_test_now(world, iid)
    assert tested["success"], f"connection test failed: {tested.get('error_message')}"
    tools = {t["name"]: t for t in tested["account_info"].get("mcp_tools", [])}
    scrape = next((n for n in tools if n.endswith("scrape")), None)
    assert scrape, f"no scrape tool among {sorted(tools)}"
    print(f"\n[discovery] {len(tools)} tools; scrape tool: {scrape}; its inputs: {tools[scrape].get('args')}")
    grant_tools(world, iid, scrape)
    pick(world, "a_admin", DMM)
    agent["m"] = Model("hi")
    send(world, "a_admin", "hello there friend")
    key = call_tool_key(agent["m"])
    agent["m"] = Model(calls((key, {"tool_name": scrape, "arguments": {"url": TARGET, "formats": ["markdown"]}})),
                       "Reported.")
    body = send(world, "a_admin", REPORTED.replace("https://gecservices.in", TARGET))
    print("[plan]", json.dumps(body["step_summaries"], indent=1))
    assert "[ROUTE] tool_execution → agent with real tool dispatch" in " ".join(body["step_summaries"])
    work = agent["m"].calls[-1][-1].content
    result = work.split(f"### {key}", 1)[-1][:1500]
    print("[tool result, first 1500 chars]", result)
    assert "FAILED" not in result.splitlines()[0], result
