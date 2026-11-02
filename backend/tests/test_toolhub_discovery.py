"""
Suite A — MCP discovery into the tool registry, against REAL local MCP servers (stdlib HTTP, streamable-HTTP style:
handshake, session id, event-stream replies). Nothing about MCP is mocked; only private-host blocking is relaxed for
the loopback servers via the dev/test setting.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.toolhub_models import McpDiscoverySnapshot, ToolEvent, ToolRecord
from tests.conftest import _run

IM = "/api/v1/integration-manager"


class LiveMcp:
    """A real MCP server whose tool list can be changed between discoveries; `down` makes it answer 503."""

    def __init__(self, tools: list[dict]):
        self.tools, self.down, self.calls = list(tools), False, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): ...

            def _send(self, code, payload=None, sid=None):
                out = b"" if payload is None else f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/event-stream")
                if sid:
                    self.send_header("Mcp-Session-Id", sid)
                self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
                if outer.down:
                    return self._send(503)
                m = body.get("method")
                if m == "initialize":
                    return self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {
                        "protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}}, sid="s1")
                if m == "notifications/initialized":
                    return self._send(202)
                if m == "tools/list":
                    return self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": outer.tools}})
                outer.calls.append(body["params"])
                return self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [
                    {"type": "text", "text": f"ran {body['params']['name']}"}]}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


def tool(name, desc="d", props=None, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props or {"q": {"type": "string"}},
                            "required": list(required)}}


@pytest.fixture()
def servers(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_mcp_hosts", True)
    made = []

    def make(tools):
        s = LiveMcp(tools)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def connect(world, url, name="Server"):
    iid = world.client.post(f"{IM}/integrations", headers=world.auth("a_admin"), json={
        "provider_type": "mcp", "display_name": name, "credentials": {"server_url": url}}).json()["id"]
    return iid


def press_test_now(world, iid):
    return world.client.post(f"{IM}/integrations/{iid}/test", headers=world.auth("a_admin")).json()


def records(world, iid, tenant=None):
    async def go():
        async with world.maker() as s:
            return {r.key: r for r in (await s.execute(select(ToolRecord).where(
                ToolRecord.tenant_id == (tenant or world.tenant_a), ToolRecord.integration_id == iid))).scalars()}
    return _run(go())


def snapshots(world, iid):
    async def go():
        async with world.maker() as s:
            return list((await s.execute(select(McpDiscoverySnapshot).where(
                McpDiscoverySnapshot.tenant_id == world.tenant_a, McpDiscoverySnapshot.integration_id == iid)
                .order_by(McpDiscoverySnapshot.created_at))).scalars())
    return _run(go())


def test_tools_are_discovered_with_real_schemas_and_registered(world, servers):
    s = servers([tool("get_keyword_ideas", "Keyword ideas", {"keyword": {"type": "string", "description": "seed"},
                                                            "limit": {"type": "integer"}}, ["keyword"]),
                 tool("send_report", "Email a report")])
    iid = connect(world, s.url)
    assert press_test_now(world, iid)["success"] is True
    recs = records(world, iid)
    assert set(recs) == {"get_keyword_ideas", "send_report"}
    schema = json.loads(recs["get_keyword_ideas"].input_schema_json)
    assert schema["required"] == ["keyword"] and schema["properties"]["limit"]["type"] == "integer"
    assert recs["get_keyword_ideas"].risk_class == "read_only" and recs["send_report"].risk_class == "external_comm"
    snap = snapshots(world, iid)[-1]
    assert snap.tool_count == 2 and sorted(json.loads(snap.added_json)) == ["get_keyword_ideas", "send_report"]


def test_added_changed_and_removed_tools_are_detected(world, servers):
    s = servers([tool("a"), tool("b")])
    iid = connect(world, s.url)
    press_test_now(world, iid)
    s.tools = [tool("a", "new description"), tool("c")]           # a changed, b removed, c added
    press_test_now(world, iid)
    snap = snapshots(world, iid)[-1]
    assert json.loads(snap.added_json) == ["c"] and json.loads(snap.removed_json) == ["b"]
    assert json.loads(snap.changed_json) == ["a"]
    recs = records(world, iid)
    assert recs["b"].status == "removed" and recs["a"].current_version == 2 and recs["a"].description == "new description"
    s.tools = [tool("a", "new description"), tool("b"), tool("c")]   # b comes back
    press_test_now(world, iid)
    assert records(world, iid)["b"].status == "active"

    async def kinds():
        async with world.maker() as db:
            return [e.kind for e in (await db.execute(select(ToolEvent).where(
                ToolEvent.tenant_id == world.tenant_a))).scalars()]
    assert {"discovered", "schema_changed", "removed"} <= set(_run(kinds()))


def test_an_unavailable_server_is_recorded_for_the_health_monitor(world, servers):
    s = servers([tool("a")])
    iid = connect(world, s.url)
    press_test_now(world, iid)
    s.down = True
    r = press_test_now(world, iid)
    assert r["success"] is False and "503" in (r["error_message"] or "")
    snap = snapshots(world, iid)[-1]
    assert snap.error and snap.tool_count == 0
    assert records(world, iid)["a"].status == "active"        # a failed discovery never deletes known tools


def test_several_servers_are_kept_apart(world, servers):
    s1, s2 = servers([tool("x_search")]), servers([tool("y_scrape"), tool("y_map")])
    i1, i2 = connect(world, s1.url, "One"), connect(world, s2.url, "Two")
    press_test_now(world, i1); press_test_now(world, i2)
    assert set(records(world, i1)) == {"x_search"} and set(records(world, i2)) == {"y_scrape", "y_map"}


def test_discovery_never_grants_and_is_tenant_scoped(world, servers):
    s = servers([tool("get_data")])
    iid = connect(world, s.url)
    press_test_now(world, iid)
    grants = world.client.get(f"{IM}/integrations/{iid}/grants", headers=world.auth("a_admin")).json()
    assert grants == []
    assert records(world, iid, tenant=world.tenant_b) == {}                    # other company sees nothing
    r = world.client.post(f"{IM}/integrations/{iid}/test", headers=world.auth("b_admin"))
    assert r.status_code == 404


def test_review_tools_refreshes_the_registry_with_full_schemas(world, servers):
    s = servers([tool("get_data", props={"site": {"type": "string"}, "days": {"type": "integer", "minimum": 1}},
                      required=["site"])])
    iid = connect(world, s.url)
    press_test_now(world, iid)
    s.tools.append(tool("get_more"))
    d = world.client.post(f"{IM}/integrations/{iid}/discover", headers=world.auth("a_admin")).json()
    assert {e["entity_name"] for e in d["entities"]} == {"get_data", "get_more"}
    recs = records(world, iid)
    assert "get_more" in recs and json.loads(recs["get_data"].input_schema_json)["properties"]["days"]["minimum"] == 1


def test_a_granted_discovered_tool_really_runs_on_the_server(world, servers):
    s = servers([tool("get_data")])
    iid = connect(world, s.url)
    press_test_now(world, iid)
    for key in ("call_tool", "mcp_tool:get_data"):
        world.client.post(f"{IM}/integrations/{iid}/grants", headers=world.auth("a_admin"),
                          json={"grants": [{"role_key": "DIGITAL_MARKETING_MANAGER", "capability_key": key}]})
    r = world.client.post(f"{IM}/integrations/{iid}/execute", headers=world.auth("a_admin"), json={
        "capability_key": "call_tool", "role_key": "DIGITAL_MARKETING_MANAGER",
        "parameters": {"tool_name": "get_data", "arguments": {"q": "x"}}})
    assert r.status_code == 200 and "ran get_data" in json.dumps(r.json()["data"])
    assert s.calls == [{"name": "get_data", "arguments": {"q": "x"}}]
