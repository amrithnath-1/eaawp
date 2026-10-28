"""
Internet tools for the chat agent: search the web and read a public web page.

web_search
    One separate model call with Google Search grounding (Gemini's built-in search). Returns the findings and the
    web pages they came from. No extra API key: it uses the configured Gemini key. With another provider it reports
    that web search is unavailable (never invents results).

read_web_page
    Fetches ONE public http(s) page and returns its readable text. Protection against server-side request forgery:
    only http/https on ports 80/443, the host must resolve to public addresses only (no loopback, private, link-local,
    reserved or cloud-metadata addresses), redirects are re-checked hop by hop (max 3), 10 s timeout, 2 MB cap.
    No cookies or credentials are ever sent.

Both are read-only and return text that the agent treats as information, never as instructions.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

WEB_SEARCH = "web_search"
READ_WEB_PAGE = "read_web_page"
WEB_TOOL_NAMES = (WEB_SEARCH, READ_WEB_PAGE)

_MAX_BYTES = 2_000_000
_MAX_TEXT = 8000
_TIMEOUT = 10.0
_MAX_REDIRECTS = 3


# ── web_search ───────────────────────────────────────────────────────────────

def _grounding_sources(meta: Any) -> list[tuple[str, str]]:
    """(title, url) pairs from Gemini grounding metadata, whatever shape the library returns."""
    if not meta:
        return []
    if not isinstance(meta, dict):
        try:
            meta = type(meta).to_dict(meta)          # proto-plus message
        except Exception:  # noqa: BLE001
            return []
    out = []
    for ch in meta.get("grounding_chunks") or meta.get("groundingChunks") or []:
        web = (ch or {}).get("web") or {}
        uri = web.get("uri") or ""
        if uri:
            out.append((web.get("title") or uri, uri))
    return list(dict.fromkeys(out))[:8]


async def search_the_web(query: str) -> str:
    from langchain_core.messages import HumanMessage

    from app.llm import get_llm_gateway

    query = " ".join(str(query or "").split())[:400]
    if not query:
        return "[TOOL ERROR] web_search: say what to search for."
    try:
        from google.ai.generativelanguage_v1beta.types import Tool as GoogleTool
        model = get_llm_gateway().get_chat_model(temperature=0)
        if "Google" not in type(model).__name__:
            return "[TOOL ERROR] web_search: web search needs the Gemini (Google) AI provider."
        resp = await model.ainvoke(
            [HumanMessage(content=(
                "Search the web and report the facts that answer this, with dates where relevant. Be concise and "
                f"factual; do not speculate.\n\nQuery: {query}"))],
            tools=[GoogleTool(google_search=GoogleTool.GoogleSearch())],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search failed (%s)", type(exc).__name__, exc_info=True)
        return f"[TOOL ERROR] web_search: the search could not be run ({type(exc).__name__})."
    text = resp.content if isinstance(resp.content, str) else " ".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in (resp.content or []))
    meta = (getattr(resp, "response_metadata", None) or {}).get("grounding_metadata")
    sources = _grounding_sources(meta)
    if not text.strip():
        return "[NO DATA] web_search: the search returned nothing."
    lines = [text.strip()[:6000]]
    if sources:
        lines.append("Sources:\n" + "\n".join(f"- {t}: {u}" for t, u in sources))
    lines.append("Source: Google Search (web)")
    return "\n\n".join(lines)


@tool(WEB_SEARCH)
async def web_search(query: str) -> str:
    """Search the internet (Google Search) for current, public information: news, competitors, market facts,
    regulations, prices, how-tos. Args: query: what to look up, in plain words. Returns findings with source links."""
    return await search_the_web(query)


# ── read_web_page ────────────────────────────────────────────────────────────

def _public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not _public_ip(str(ip.ipv4_mapped))))


async def _check_url(url: str) -> str | None:
    """None when the URL may be fetched, else the reason it may not."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "only public http(s) web pages can be read"
    if parts.username or parts.password:
        return "addresses with credentials are not allowed"
    if parts.port not in (None, 80, 443):
        return "only the standard web ports are allowed"
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443,
                                                             type=socket.SOCK_STREAM)
    except OSError:
        return "the site's address could not be found"
    addrs = {i[4][0] for i in infos}
    if not addrs or not all(_public_ip(a) for a in addrs):
        return "that address is not a public website"
    return None


def _readable_text(raw: str) -> tuple[str, str]:
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_m.group(1))).strip() if title_m else ""
    body = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw)
    body = re.sub(r"(?is)<!--.*?-->", " ", body)
    body = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr)\s*/?>", "\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html.unescape(body)
    body = "\n".join(" ".join(line.split()) for line in body.splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body


async def fetch_page(url: str) -> str:
    import httpx

    url = str(url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    for _ in range(_MAX_REDIRECTS + 1):
        problem = await _check_url(url)
        if problem:
            return f"[TOOL ERROR] read_web_page: {problem}."
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False,
                                         headers={"User-Agent": "EAAWP-reader/1.0"}) as client:
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        url = urljoin(url, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        return f"[TOOL ERROR] read_web_page: the site answered HTTP {resp.status_code}."
                    ctype = resp.headers.get("content-type", "")
                    if "html" not in ctype and "text" not in ctype and "json" not in ctype:
                        return f"[TOOL ERROR] read_web_page: not a readable page ({ctype or 'unknown type'})."
                    data = b""
                    async for chunk in resp.aiter_bytes():
                        data += chunk
                        if len(data) > _MAX_BYTES:
                            break
                    raw = data.decode(resp.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            return f"[TOOL ERROR] read_web_page: the page could not be loaded ({type(exc).__name__})."
        if "json" in ctype:
            title, text = "", raw
        else:
            title, text = _readable_text(raw)
        if not text:
            return "[NO DATA] read_web_page: the page has no readable text."
        cut = len(text) > _MAX_TEXT
        return (f"Page: {title or url}\nURL: {url}\n\n{text[:_MAX_TEXT]}"
                + ("\n\n[…page text shortened]" if cut else "") + f"\n\nSource: {url}")
    return "[TOOL ERROR] read_web_page: too many redirects."


@tool(READ_WEB_PAGE)
async def read_web_page(url: str) -> str:
    """Read the text of one public web page (for example the company's own site, a competitor's page or an article
    found with web_search). Args: url: the page address, e.g. https://gecservices.in/services."""
    return await fetch_page(url)


WEB_TOOLS = {WEB_SEARCH: web_search, READ_WEB_PAGE: read_web_page}
