"""
What a message about a connected service is asking for, before anything answers it.

A request that names a connected service is one of several different things, and each needs a different path:

  connection_status       "Is Firecrawl connected?"                      → status card from the stored record
  connection_management   "Connect GitHub", "disconnect the MCP server"   → the existing connection flow (cards / forms)
  tool_discovery          "What tools does Firecrawl provide?"           → the tool registry, with real input schemas
  tool_execution          "Use Firecrawl to scrape my website"           → permission check → the agent → real dispatch
  multi_tool_execution    "Scrape these three URLs"                      → as above, several calls
  diagnostics             "Diagnose why Firecrawl failed"                → recorded failures, error classes, live check
  permission_check        "Which employees can use Firecrawl?"           → the grants that exist
  permission_change       "Grant the marketing employee Firecrawl"       → the existing grant flow (approval)

The old pre-flight matched words such as "connected", "integration" or "mcp" and answered every such message with a
connection card, so "Inspect the connected Firecrawl MCP integration, discover its tools and execute a scrape" was
answered with "already connected" and nothing ran. Words describing a service ("the connected X") are not a request
about the connection; what the person wants done is decided by the verbs, with execution > diagnostics > permission >
discovery > status > management when one message asks for several things (the strongest one includes the others).

Deterministic and model-free: nothing here depends on a provider name. Service names come from the company's own
integrations (their display names) and the generic provider words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CONNECTION_STATUS = "connection_status"
CONNECTION_MANAGEMENT = "connection_management"
TOOL_DISCOVERY = "tool_discovery"
TOOL_EXECUTION = "tool_execution"
MULTI_TOOL_EXECUTION = "multi_tool_execution"
DIAGNOSTICS = "diagnostics"
PERMISSION_CHECK = "permission_check"
PERMISSION_CHANGE = "permission_change"

EXECUTION_ROUTES = frozenset({TOOL_EXECUTION, MULTI_TOOL_EXECUTION})

# Generic words for kinds of services (no product the company may connect is special-cased).
_PROVIDER_WORDS = {
    "mcp": r"mcp|model context protocol|mcp server",
    "github": r"git ?hub",
    "google_search_console": r"google search console|search console|gsc",
    "google_analytics": r"google analytics|ga4",
    "facebook": r"facebook|meta ads|instagram ads",
    "postgresql": r"postgres(?:ql)?",
    "mysql": r"mysql|mariadb",
}
_PROVIDER_RES = {k: re.compile(rf"\b({v})\b") for k, v in _PROVIDER_WORDS.items()}
_GENERIC_SERVICE = re.compile(r"\b(integrations?|connectors?|connected (services?|tools?|apps?)|mcp tools?)\b")
# Tokens of a display name that say nothing about which service it is.
_NAME_STOP = {"server", "servers", "mcp", "the", "and", "for", "api", "tool", "tools", "integration", "connection",
              "app", "service", "my", "our", "data", "http", "https", "remote", "local", "test", "prod", "production"}

_URL = re.compile(r"\bhttps?://[^\s<>\"')]+|\b(?:[a-z0-9-]+\.)+(?:com|in|org|net|io|co|ai|dev|app|uk|us|info|biz)\b"
                  r"(?:/[^\s<>\"')]*)?", re.I)

# What the person wants DONE with a service's tools.
_EXEC = re.compile(
    r"\b(scrape|scraping|scraped|crawl|crawling|extract|extracting|execute|executing|run|running|invoke|invoking|"
    r"call|calling|use|using|fetch|fetching|retrieve|pull|search|searching|map|mapping|screenshot|summari[sz]e|"
    r"read|download|look ?up|query)\b")
# Execution verbs that are really about the connection ("run a connection test", "use the status page").
_EXEC_ABOUT_CONNECTION = re.compile(
    r"\b(run|execute|use|call)\b\W+(\w+\W+){0,3}?(connection|status|health)\s*(test|check)?\b")
_MULTI = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|several|multiple|many|each of|all of|\d+)\s+(\w+\s+){0,2}?"
    r"(urls?|sites?|websites?|pages?|links?|domains?|competitors?|tools?)\b")

_DIAG = re.compile(
    r"\b(diagnos\w*|troubleshoot\w*|debug\w*|root cause)\b"
    r"|\bwhy\b.{0,80}\b(fail\w*|error\w*|time[sd]? ?out|timing out|not work\w*|broken|break\w*|refus\w*|stuck|slow)\b"
    r"|\bwhat went wrong\b|\b(fix|investigate|explain)\b.{0,40}\b(failure|error|timeout|time ?out)\b")
# "grant"/"revoke" as verbs; "without a grant", "the grant", "no grant" are nouns (a permission question or test).
_PERM_CHANGE_STRONG = re.compile(
    r"(?<!\ba )(?<!\ban )(?<!the )(?<!no )(?<!any )(?<!its )(?<!their )(?<!this )(?<!that )"
    r"\b(grant|revoke|un-?grant)\b(?!\s*(s|ed|is|was|exists?|record\w*|list)\b)"
    r"|\b(remove (the )?access|take away (the )?access)\b")
_PERM_CHANGE = re.compile(
    r"\b(give)\b.{0,80}\b(access|permissions?)\b"
    r"|\b(allow|let)\b.{0,60}\b(to use|to access|to run|use|access)\b")
_PERM_CHECK = re.compile(
    r"\b(who|which|what|check|verify|list|show|does|do|is|are|can|has|have)\b.{0,80}"
    r"\b(access|permissions?|allowed|granted|grants?|authori[sz]ed|entitle\w*)\b"
    r"|\bcan\b.{0,40}\b(employees?|managers?|assistants?|analysts?|clerks?|agents?|roles?|staff|team)\b.{0,20}"
    r"\b(use|access|run|call)\b"
    r"|\b(who|which|what)\b.{0,40}\b(employees?|managers?|assistants?|analysts?|clerks?|agents?|roles?|staff)\b"
    r".{0,20}\b(can|may|are allowed to|is allowed to)\b.{0,10}\b(use|access|run|call)\b")
_DISCOVERY = re.compile(
    r"\b(what|which|list|show|discover\w*|enumerate|inspect|review|get|see|display|tell me)\b.{0,50}"
    r"\b(tools?|capabilit(y|ies)|functions?|actions?|operations?|endpoints?|schemas?)\b"
    r"|\bwhat\b.{0,40}\b(can|does|do)\b.{0,40}\b(do|provide|offer|support|expose)\b"
    r"|\btools?\b.{0,40}\b(provide[sd]?|offer(s|ed)?|available|expose[sd]?|have|has)\b")
_STATUS = re.compile(
    r"\b(is|are|was)\b.{0,60}\b(connected|working|online|up|active|enabled|reachable|healthy|live)\b"
    r"|\b(status|connection state|health)\b|\btest\b.{0,30}\bconnection\b|\bconnection\b.{0,20}\btest\b"
    r"|\b(check|verify)\b.{0,30}\b(connection|connected)\b")
_MANAGE = re.compile(
    r"\b(connect|connecting|integrate|link|set ?up|authori[sz]e|enable|disable|disconnect|unlink|reconnect|"
    r"remove integration|add (an? )?(new )?(integration|connection|server))\b")


@dataclass
class ServiceRef:
    id: str
    display_name: str
    provider_type: str
    status: str


@dataclass
class RouteDecision:
    route: str | None                       # one of the constants above, or None (not about a connected service)
    services: list[ServiceRef] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)   # why — recorded in the plan for audit

    @property
    def is_execution(self) -> bool:
        return self.route in EXECUTION_ROUTES


def _name_tokens(display_name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", display_name.lower()) if len(t) >= 4 and t not in _NAME_STOP]


def resolve_services(text: str, integrations: list[dict]) -> tuple[list[ServiceRef], bool]:
    """The company's integrations the message names (by display name, or by kind), and whether a kind/generic
    service word was used."""
    t = text.lower()
    named: list[ServiceRef] = []
    generic = bool(_GENERIC_SERVICE.search(t))
    kinds = {k for k, rx in _PROVIDER_RES.items() if rx.search(t)}
    for i in integrations:
        ref = ServiceRef(str(i.get("id")), str(i.get("display_name") or ""), str(i.get("provider_type") or ""),
                         str(i.get("status") or ""))
        full = ref.display_name.lower().strip()
        by_name = bool(full) and (re.search(rf"\b{re.escape(full)}\b", t) is not None
                                  or any(re.search(rf"\b{re.escape(tok)}\b", t) for tok in _name_tokens(full)))
        if by_name:
            named.append(ref)
    if not named and kinds:
        named = [ServiceRef(str(i.get("id")), str(i.get("display_name") or ""), str(i.get("provider_type") or ""),
                            str(i.get("status") or "")) for i in integrations if i.get("provider_type") in kinds]
    return named, bool(kinds) or generic


# Specific execution verbs whose stem can be matched against the names of tools a role is granted
# ("scrape" → a tool named *scrape*). Generic verbs (use, run, get) never select a service on their own.
_SPECIFIC_VERBS = {"scrape": "scrap", "scraping": "scrap", "scraped": "scrap", "crawl": "crawl", "crawling": "crawl",
                   "extract": "extract", "extracting": "extract", "screenshot": "screenshot", "map": "map",
                   "mapping": "map"}


def classify(text: str, integrations: list[dict] | None = None,
             granted_tools: dict[str, list[str]] | None = None) -> RouteDecision:
    """Decide what a message about a connected service asks for. route=None when it is not about one.

    granted_tools: {integration_id: [tool names this AI employee may run]} — lets "scrape gecservices.in" (no service
    named) go to the service whose granted tool does exactly that.
    """
    t = " ".join((text or "").lower().split())
    integrations = integrations or []
    services, kind_word = resolve_services(t, integrations)
    if not services and not kind_word and granted_tools:
        stems = {_SPECIFIC_VERBS[w] for w in re.findall(r"[a-z]+", t) if w in _SPECIFIC_VERBS}
        hit = {iid for iid, names in granted_tools.items()
               if any(stem in re.split(r"[^a-z0-9]+", n.lower()) or any(tok.startswith(stem) for tok in
                                                                        re.split(r"[^a-z0-9]+", n.lower()))
                      for stem in stems for n in names)}
        services = [ServiceRef(str(i.get("id")), str(i.get("display_name") or ""), str(i.get("provider_type") or ""),
                               str(i.get("status") or "")) for i in integrations if str(i.get("id")) in hit]
    if not services and not kind_word and _PERM_CHECK.search(t) and re.search(r"\btools?\b", t):
        services = [ServiceRef(str(i.get("id")), str(i.get("display_name") or ""), str(i.get("provider_type") or ""),
                               str(i.get("status") or "")) for i in integrations]
        kind_word = True
    if not services and not kind_word:
        return RouteDecision(None)
    urls = [u.rstrip(".,;:!?") for u in _URL.findall(t)]
    signals: list[str] = []

    exec_hit = bool(_EXEC.search(t)) and not (_EXEC_ABOUT_CONNECTION.search(t) and len(_EXEC.findall(t)) == 1)
    # "run" / "use" alone with a permission question is a permission question ("can the clerk use X").
    perm_check = bool(_PERM_CHECK.search(t))
    perm_change_strong = bool(_PERM_CHANGE_STRONG.search(t))
    perm_change = perm_change_strong or bool(_PERM_CHANGE.search(t))
    diag = bool(_DIAG.search(t))
    discovery = bool(_DISCOVERY.search(t))
    status = bool(_STATUS.search(t))
    manage = bool(_MANAGE.search(t))

    if diag:
        signals.append("diagnostic wording")
        route = DIAGNOSTICS
    elif perm_change_strong or (perm_change and not exec_hit):
        signals.append("grant/revoke wording")
        route = PERMISSION_CHANGE
    elif perm_check and not (exec_hit and (urls or _MULTI.search(t)) ):
        signals.append("access question")
        route = PERMISSION_CHECK
    elif exec_hit:
        verbs = sorted(set(_EXEC.findall(t)))
        signals.append("execution verbs: " + ", ".join(verbs[:5]))
        if urls:
            signals.append(f"{len(urls)} target(s)")
        multi = len(urls) >= 2 or bool(_MULTI.search(t))
        route = MULTI_TOOL_EXECUTION if multi else TOOL_EXECUTION
    elif discovery:
        signals.append("asks which tools exist")
        route = TOOL_DISCOVERY
    elif status:
        signals.append("asks about the connection state")
        route = CONNECTION_STATUS
    elif manage:
        signals.append("connection management verb")
        route = CONNECTION_MANAGEMENT
    else:
        return RouteDecision(None, services, urls, ["names a service but asks nothing specific about it"])
    return RouteDecision(route, services, urls, signals)
