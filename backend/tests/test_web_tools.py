"""Internet tools: web search (Gemini Google Search grounding) and reading a public page safely.

FAKED: DNS answers, the HTTP server (httpx MockTransport) and the language model. Real: the tool code and the agent.
"""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.tools import web_tools as wt


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def dns(monkeypatch):
    table = {"gecservices.in": "93.184.216.34", "evil.example": "10.0.0.5", "meta.example": "169.254.169.254",
             "local.example": "127.0.0.1", "v6.example": "::1"}

    async def fake(self, host, port, **k):
        if host not in table:
            raise socket.gaierror("unknown")
        fam = socket.AF_INET6 if ":" in table[host] else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (table[host], port))]
    monkeypatch.setattr(asyncio.AbstractEventLoop, "getaddrinfo", fake, raising=False)
    import asyncio.base_events as be
    monkeypatch.setattr(be.BaseEventLoop, "getaddrinfo", fake)
    return table


@pytest.fixture()
def site(monkeypatch):
    pages = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body, status, headers = pages.get(str(request.url), ("", 404, {}))
        return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8", **headers})
    real = httpx.AsyncClient

    def client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return pages


@pytest.mark.parametrize("url,reason", [
    ("ftp://gecservices.in/x", "only public http(s)"),
    ("https://evil.example/", "not a public website"),
    ("https://meta.example/latest/meta-data", "not a public website"),
    ("http://local.example/", "not a public website"),
    ("http://v6.example/", "not a public website"),
    ("https://user:pw@gecservices.in/", "credentials"),
    ("https://gecservices.in:8443/", "standard web ports"),
    ("https://nowhere.example/", "could not be found"),
])
def test_private_and_odd_addresses_are_refused(dns, url, reason):
    out = run(wt.fetch_page(url))
    assert out.startswith("[TOOL ERROR]") and reason in out, out


def test_a_public_page_is_read_as_text(dns, site):
    site["https://gecservices.in/"] = ("<html><head><title>GEC Services</title><script>var x=1</script></head>"
                                       "<body><h1>We Handle the Process.</h1><p>Passport &amp; visa help.</p></body>"
                                       "</html>", 200, {})
    out = run(wt.fetch_page("gecservices.in/"))
    assert "Page: GEC Services" in out and "We Handle the Process." in out and "Passport & visa help." in out
    assert "var x" not in out and out.rstrip().endswith("Source: https://gecservices.in/")


def test_a_redirect_into_a_private_network_is_refused(dns, site):
    site["https://gecservices.in/go"] = ("", 302, {"location": "https://evil.example/admin"})
    out = run(wt.fetch_page("https://gecservices.in/go"))
    assert "not a public website" in out


def test_web_search_returns_findings_with_sources(monkeypatch):
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway

    class ChatGoogleFake:
        async def ainvoke(self, messages, tools=None, **k):
            self.tools = tools
            return AIMessage(content="GEC Services is a document-service centre in Kerala.",
                             response_metadata={"grounding_metadata": {"grounding_chunks": [
                                 {"web": {"uri": "https://gecservices.in/", "title": "gecservices.in"}}]}})
    ChatGoogleFake.__name__ = "ChatGoogleGenerativeAI"
    m = ChatGoogleFake()
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: m)
    out = run(wt.search_the_web("what is GEC Services"))
    assert "document-service centre" in out and "- gecservices.in: https://gecservices.in/" in out
    assert "google_search" in str(m.tools[0])


def test_web_search_without_gemini_says_so(monkeypatch):
    from app.llm.gateway import LLMGateway

    class ChatOpenAI:
        async def ainvoke(self, *a, **k):
            raise AssertionError("must not be called")
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: ChatOpenAI())
    assert "needs the Gemini" in run(wt.search_the_web("anything"))


def test_the_agent_gets_web_tools_except_the_medical_role(world, monkeypatch):
    import app.config as cfg
    from tests.test_chat_agent import Script, pick, send
    from types import SimpleNamespace
    from app.llm.gateway import LLMGateway
    cfg.settings.__dict__["chat_engine"] = "agent"
    holder = {"m": Script("ok")}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    pick(world, "a_admin", "DIGITAL_MARKETING_MANAGER")
    send(world, "a_admin", "who are our competitors")
    assert {"web_search", "read_web_page"} <= set(holder["m"].tools)


def test_grounding_accepts_figures_computed_from_the_data_but_not_invented_ones():
    from app.services.grounding import ungrounded_figures
    ev = ('[{"query":"passport","clicks":120,"impressions":3000,"ctr":0.04,"position":5.2},'
          '{"query":"visa","clicks":80,"impressions":2000,"ctr":0.04,"position":7.1}]')
    ok = ("Total clicks 200 from 5,000 impressions, CTR 4%, average position 6.15; "
          "passport got 50% more clicks than visa (40 more).")
    assert ungrounded_figures(ok, ev) == []
    assert ungrounded_figures("You got 1,234 clicks and a 9.7% CTR", ev) == ["1,234", "9.7%"]
