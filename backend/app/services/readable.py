"""
Data a person can read: integration results as tables with plain column names and human numbers.

Integration tools hand the model rows like ``query: community certificate | clicks: 2 | impressions: 1156 |
ctr: 0.0017301038062283738 | position: 9.666089965397925``. That is fine for the model, unreadable for an office
user. ``tables_from_evidence`` turns the same text into Markdown tables:

    | Query | Clicks | Impressions | Click-through rate | Avg. position |
    | community certificate | 2 | 1,156 | 0.17% | 9.7 |

Nothing is computed or invented here: values are only formatted (rates as %, positions to one decimal, thousands
separators), and the totals line is the one the tool itself returned.
"""
from __future__ import annotations

import re

MAX_ROWS = 25

_LABELS = {
    "ctr": "Click-through rate", "position": "Avg. position", "site_url": "Website", "permission": "Access",
    "query": "Search query", "page": "Page", "country": "Country", "device": "Device", "date": "Date",
    "clicks": "Clicks", "impressions": "Impressions", "sessions": "Sessions", "users": "Users",
    "pageviews": "Page views", "bounce_rate": "Bounce rate", "conversions": "Conversions",
    "full_name": "Repository", "html_url": "Link", "stargazers_count": "Stars", "open_issues_count": "Open issues",
}
_CAP_TITLES = {
    "get_search_analytics": "Search performance", "list_sites": "Websites in Search Console",
    "list_properties": "Analytics properties", "run_report": "Website traffic", "list_repositories": "Repositories",
}
_ROW = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_HEADER = re.compile(r"^\[(?P<tool>[^\]]+)\]\s*(?P<rest>.*)$")
_PERMISSIONS = {"siteOwner": "Owner", "siteFullUser": "Full access", "siteRestrictedUser": "Restricted access",
                "siteUnverifiedUser": "Not verified"}
_RATE_KEYS = ("ctr", "rate", "share", "ratio", "percent")


def label(key: str) -> str:
    k = key.strip()
    return _LABELS.get(k.lower(), k.replace("_", " ").strip().capitalize())


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def value(key: str, raw: str) -> str:
    """One value, formatted for a person (never changed, only rounded for display)."""
    raw = raw.strip()
    if key.lower() == "permission" and raw in _PERMISSIONS:
        return _PERMISSIONS[raw]
    n = _num(raw)
    if n is None:
        return raw.replace("|", "/")
    k = key.lower()
    if any(r in k for r in _RATE_KEYS) and 0 <= n <= 1:
        pct = n * 100
        return f"{pct:.2f}%" if pct < 1 else f"{pct:.1f}%"
    if k == "position" or k.endswith("_position"):
        return f"{n:.1f}"
    if n.is_integer():
        return f"{int(n):,}" if abs(n) >= 10000 or "," in raw or k in ("impressions", "clicks", "sessions") \
            else str(int(n))
    return f"{n:,.2f}" if abs(n) >= 1 else f"{n:.3g}"


def _blocks(evidence: str) -> list[dict]:
    blocks: list[dict] = []
    cur: dict | None = None
    for line in (evidence or "").splitlines():
        h = _HEADER.match(line.strip())
        if h and ("Integration:" in h.group("rest") or "Source:" in h.group("rest")):
            cur = {"tool": h.group("tool"), "source": "", "cap": "", "rows": [], "notes": []}
            blocks.append(cur)
            rest = h.group("rest")
            if "Source:" in rest:
                cur["source"] = rest.split("Source:", 1)[1].split("Capability:")[0].strip()
            if "Capability:" in rest:
                cur["cap"] = rest.split("Capability:", 1)[1].split()[0].strip()
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("Source:") and not cur["source"]:
            cur["source"] = s.split(":", 1)[1].strip()
        elif s.startswith("Capability:"):
            cur["cap"] = s.split(":", 1)[1].strip().split()[0]
        elif (m := _ROW.match(line)) and ": " in m.group(2):
            fields = []
            for part in m.group(2).split(" | "):
                if ": " in part:
                    k, v = part.split(": ", 1)
                    fields.append((k.strip(), v.strip()))
            if fields:
                cur["rows"].append(fields)
        elif s.startswith(("Total ", "Overall ")):
            cur["notes"].append(s)
    return [b for b in blocks if b["rows"]]


def _note(text: str) -> str:
    """'Overall CTR across these rows (total clicks / total impressions): 1.66%' → plain words."""
    t = re.sub(r"\s*\(total clicks / total impressions\)", "", text)
    t = t.replace("Overall CTR", "Overall click-through rate").replace(" across the ", " in the ")
    return t.replace(" rows above", " rows").replace(" across these rows", "")


def tables_from_evidence(evidence: str) -> str:
    """Markdown tables for every block of integration rows in ``evidence`` ('' when there are none)."""
    out: list[str] = []
    for b in _blocks(evidence):
        keys: list[str] = []
        for row in b["rows"]:
            for k, _ in row:
                if k not in keys:
                    keys.append(k)
        title = _CAP_TITLES.get(b["cap"], label(b["cap"]) if b["cap"] else "Data")
        src = f" — {b['source']}" if b["source"] else ""
        lines = [f"**{title}**{src}", "", "| " + " | ".join(label(k) for k in keys) + " |",
                 "|" + "---|" * len(keys)]
        for row in b["rows"][:MAX_ROWS]:
            d = dict(row)
            lines.append("| " + " | ".join(value(k, d.get(k, "")) if k in d else "" for k in keys) + " |")
        if len(b["rows"]) > MAX_ROWS:
            lines.append(f"\n…and {len(b['rows']) - MAX_ROWS} more rows.")
        notes = [_note(n) for n in b["notes"] if n.startswith(("Total ", "Overall "))]
        if notes:
            lines += ["", " · ".join(notes)]
        out.append("\n".join(lines))
    return "\n\n".join(out)
