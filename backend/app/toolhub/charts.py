"""
Visualization specs for analytical answers, built only from verified data.

build(raw, evidence) checks the requested chart and returns a ChartSpec (see docs/TOOLHUB_API.md) or a reason:
- shape: labels and one value per label for every series; numbers or null only; size limits;
- truth: every number must be found in, or computed like-with-like from, the tool results of the same answer
  (the same grounding check the written answer gets) — a chart can never show data the tools did not return;
- type: chosen from the data when not given (dates → line, a few shares → donut, x/y pairs → scatter, else bar).
A chart that fails is reported to the model; the written answer is still delivered.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.services.grounding import ungrounded_figures

TYPES = ("bar", "hbar", "line", "area", "pie", "donut", "scatter", "histogram", "kpi", "table")
_ALIASES = {"column": "bar", "columns": "bar", "vertical_bar": "bar", "grouped_bar": "bar", "grouped": "bar",
            "comparison": "bar", "stacked_bar": "bar", "stacked": "bar", "horizontal_bar": "hbar", "barh": "hbar",
            "horizontal": "hbar", "bar_horizontal": "hbar", "stacked_area": "area", "doughnut": "donut",
            "hist": "histogram", "distribution": "histogram", "kpis": "kpi", "metrics": "kpi", "cards": "kpi",
            "kpi_cards": "kpi", "timeseries": "line", "time_series": "line", "trend": "line", "points": "scatter"}
MAX_BINS = 30
MAX_LABELS, MAX_SERIES = 200, 8
_DATE = re.compile(r"^(\d{4}-\d{2}(-\d{2})?|\d{1,2}/\d{1,2}(/\d{2,4})?|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                   r"[a-z]*\.?(\s+\d{2,4})?|q[1-4](\s+\d{4})?|week\s*\d+|\d{4})$", re.I)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("%", "").strip())
        except ValueError:
            return None
    return None


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(round(v, 6))


def _is_pct(unit: Any, name: Any) -> bool:
    text = f"{unit or ''} {name or ''}".lower()
    return "%" in text or any(w in text for w in ("percent", "share", "rate", "ctr", "ratio"))


def choose_type(labels: list[str], series: list[dict]) -> str:
    if len(series) == 2 and not labels:
        return "scatter"
    if labels and sum(1 for l in labels if _DATE.match(l.strip())) >= max(2, len(labels) * 0.8):
        return "line"
    if len(series) == 1 and 2 <= len(labels) <= 6:
        vals = [v for v in series[0]["values"] if v is not None]
        total = sum(vals)
        name = (series[0].get("name") or "").lower()
        if vals and min(vals) >= 0 and (abs(total - 100) <= 1.5 or "share" in name or "percent" in name):
            return "donut"
    if len(series) == 1 and labels and (len(labels) > 8 and sum(len(l) for l in labels) / len(labels) > 14):
        return "hbar"
    return "bar"


def normalize(raw: Any) -> dict | None:
    """Common shapes a model writes (labels/categories/x, series/datasets/data/values, chart_type, …) → our input
    shape. Values are only moved, never invented. None when the object is not a chart."""
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("chart"), dict) and len(raw) <= 2:
        raw = raw["chart"]
    out = dict(raw)
    t = str(raw.get("type") or raw.get("chart_type") or raw.get("chartType") or raw.get("kind") or "").lower()
    t = t.replace("-", "_").replace(" ", "_")
    if t.startswith("stacked") or raw.get("stacked") is True:
        out["stacked"] = True
    out["type"] = _ALIASES.get(t, t)
    if not out.get("labels"):
        for k in ("categories", "x", "xAxis", "x_values", "dates"):
            if isinstance(raw.get(k), list) and all(not isinstance(v, (dict, list)) for v in raw[k]):
                out["labels"] = raw[k]
                break
    if not out.get("series"):
        if isinstance(raw.get("datasets"), list):
            out["series"] = [{"name": d.get("label") or d.get("name"), "values": d.get("data") or d.get("values")}
                             for d in raw["datasets"] if isinstance(d, dict)]
        elif isinstance(raw.get("data"), list) and raw["data"] and all(isinstance(d, dict) for d in raw["data"]):
            rows = raw["data"]
            lk = next((k for k in ("label", "name", "category", "x", "date", "key") if k in rows[0]), None)
            vks = [k for k in rows[0] if k != lk and isinstance(_num(rows[0][k]), float)]
            if lk and vks:
                out["labels"] = [r.get(lk) for r in rows]
                out["series"] = [{"name": k if k not in ("value", "y") else (raw.get("y_label") or "Value"),
                                  "values": [r.get(k) for r in rows]} for k in vks]
        elif isinstance(raw.get("values"), list):
            out["series"] = [{"name": raw.get("y_label") or raw.get("name") or "Value", "values": raw["values"]}]
    if isinstance(out.get("series"), list):
        out["series"] = [s if isinstance(s, dict) else {"name": "Value", "values": s} for s in out["series"]]
        for s_ in out["series"]:
            if "values" not in s_ and isinstance(s_.get("data"), list):
                s_["values"] = s_["data"]
    if isinstance(raw.get("kpis"), dict):
        out["kpis"] = [{"label": k, "value": v} for k, v in raw["kpis"].items()]
    chartish = bool(out.get("series") or out.get("kpis")) and bool(out.get("title") or out.get("type"))
    if not chartish:
        return None
    if not out.get("title"):
        out["title"] = str(out.get("y_label") or out.get("type") or "Chart").replace("_", " ").title()
    return out


def _histogram(raw: dict) -> tuple[list[str], list[dict], list[float]] | str:
    vals = [v for v in (_num(x) for x in raw.get("raw_values") or raw.get("values") or
                        ((raw.get("series") or [{}])[0] or {}).get("values") or []) if v is not None]
    if len(vals) < 2:
        return "a histogram needs at least 2 numeric values"
    lo, hi = min(vals), max(vals)
    n = int(_num(raw.get("bins")) or 0) or min(MAX_BINS, max(5, round(len(vals) ** 0.5)))
    n = max(1, min(n, MAX_BINS))
    if hi == lo:
        return [_fmt(lo)], [{"name": "Count", "values": [float(len(vals))]}], vals
    width = (hi - lo) / n
    counts = [0.0] * n
    for v in vals:
        counts[min(int((v - lo) / width), n - 1)] += 1
    labels = [f"{_fmt(round(lo + i * width, 4))}–{_fmt(round(lo + (i + 1) * width, 4))}" for i in range(n)]
    return labels, [{"name": "Count", "values": counts}], vals


def build(raw: dict, evidence: str) -> tuple[dict | None, str]:
    if isinstance(raw, dict):
        raw = normalize(raw) or raw
    if not isinstance(raw, dict):
        return None, "chart must be an object"
    title = " ".join(str(raw.get("title") or "").split())[:120]
    if not title:
        return None, "chart needs a title"
    ctype = str(raw.get("type") or "").lower()
    kpis_in = raw.get("kpis") or []
    if ctype == "kpi" or (kpis_in and not raw.get("series")):
        kpis = []
        for k in kpis_in[:12]:
            v = _num((k or {}).get("value"))
            if v is None or not (k or {}).get("label"):
                return None, "every KPI needs a label and a numeric value"
            kpis.append({"label": str(k["label"])[:60], "value": v, "unit": (str(k.get("unit"))[:20] if k.get("unit") else None)})
        values = [(k["value"], _is_pct(k["unit"], k["label"])) for k in kpis]
        series, labels, ctype = [], [], "kpi"
    elif ctype == "histogram":
        h = _histogram(raw)
        if isinstance(h, str):
            return None, h
        labels, series, raw_vals = h
        # The bins are counted here from the values; the VALUES are what must come from the tools.
        values = [(v, _is_pct(raw.get("unit"), raw.get("x_label"))) for v in raw_vals]
        kpis = []
    else:
        labels = [str(l)[:60] for l in (raw.get("labels") or [])][:MAX_LABELS]
        series = []
        for s in (raw.get("series") or [])[:MAX_SERIES]:
            vals = [_num(v) for v in (s or {}).get("values") or []]
            if labels and len(vals) != len(labels):
                return None, f"series '{(s or {}).get('name')}' has {len(vals)} values for {len(labels)} labels"
            series.append({"name": str((s or {}).get("name") or "Value")[:60], "values": vals})
        if not series or not any(v is not None for s in series for v in s["values"]):
            return None, "chart needs at least one series with numbers"
        if not labels and ctype != "scatter" and not (len(series) == 2 and not ctype):
            return None, "chart needs labels (categories or dates) for its values"
        ctype = ctype if ctype in TYPES else choose_type(labels, series)
        pct_chart = _is_pct(raw.get("unit"), raw.get("y_label"))
        values = [(v, pct_chart or _is_pct(None, s["name"])) for s in series for v in s["values"] if v is not None]
        kpis = []
    bad = ungrounded_figures(" ".join(_fmt(v) + ("%" if pct else "") for v, pct in values), evidence or "")
    if bad:
        return None, (f"these values are not in the data your tools returned: {', '.join(bad[:6])}. "
                      "Charts may only show returned data (or totals/ratios computed from it).")
    return {
        "id": str(uuid.uuid4()), "type": ctype, "title": title,
        "unit": (str(raw.get("unit"))[:20] if raw.get("unit") else None),
        "x_label": (str(raw.get("x_label"))[:60] if raw.get("x_label") else None),
        "y_label": (str(raw.get("y_label"))[:60] if raw.get("y_label") else None),
        "description": (" ".join(str(raw.get("description")).split())[:300] if raw.get("description") else None),
        "stacked": bool(raw.get("stacked")) and ctype in ("bar", "hbar", "area") and len(series) > 1,
        "labels": labels, "series": series, "kpis": kpis,
        "source": str(raw.get("source") or "Data returned by the tools used in this answer")[:200],
        "note": (str(raw.get("note"))[:300] if raw.get("note") else None),
    }, ""


# ── Charts written into an answer's text ─────────────────────────────────────

_FENCE = re.compile(r"```[ \t]*(json|chart|javascript|js)?[ \t]*\n(.*?)\n?```", re.S | re.I)


def _table(raw: dict) -> str:
    labels = [str(l) for l in (raw.get("labels") or [])][:30]
    series = [s for s in (raw.get("series") or []) if isinstance(s, dict)][:6]
    if raw.get("kpis") and not series:
        rows = [f"| {k.get('label', '')} | {k.get('value', '')}{(' ' + str(k['unit'])) if k.get('unit') else ''} |"
                for k in raw["kpis"][:20] if isinstance(k, dict)]
        return "| Measure | Value |\n|---|---|\n" + "\n".join(rows) if rows else ""
    if not labels or not series:
        return ""
    head = "| " + " | ".join([str(raw.get("x_label") or "Item")] + [str(s.get("name") or "Value") for s in series]) + " |"
    sep = "|" + "---|" * (len(series) + 1)
    body = []
    for i, l in enumerate(labels):
        cells = []
        for s in series:
            vals = s.get("values") or []
            cells.append("" if i >= len(vals) or vals[i] is None else str(vals[i]))
        body.append("| " + " | ".join([l] + cells) + " |")
    return "\n".join([head, sep, *body])


def extract_from_text(text: str, evidence: str, limit: int = 6) -> tuple[str, list[dict], list[str]]:
    """Chart objects a model wrote into its answer (fenced JSON, or a bare JSON object on its own lines).

    Each one is validated exactly like make_chart. A valid one becomes a chart and is removed from the text; one that
    cannot be drawn is replaced by a readable table of what it contained and the reason — the person never sees raw
    chart JSON. Returns (clean text, charts, problems). Text without chart objects is returned unchanged.
    """
    if not text or "{" not in text:
        return text, [], []
    charts_out: list[dict] = []
    problems: list[str] = []

    def handle(blob: str) -> str | None:
        try:
            obj = json.loads(blob)
        except ValueError:
            return None
        items = obj if isinstance(obj, list) else [obj]
        norm = [normalize(o) for o in items]
        if not items or any(n is None for n in norm):
            return None                                     # not chart JSON: leave it alone
        replacement = []
        for n in norm:
            if len(charts_out) >= limit:
                break
            spec, why = build(n, evidence)
            if spec is not None:
                charts_out.append(spec)
                replacement.append(f"*(Chart: {spec['title']} — shown below.)*")
            else:
                problems.append(why)
                # Values that are not in the tools' data are not shown at all, not even as a table.
                unverified = "not in the data" in why
                tbl = "" if unverified else _table(n)
                shown = ("its numbers are not in the data the tools returned, so it is not shown" if unverified
                         else why)
                replacement.append(f"**{n.get('title', 'Chart')}** — the chart could not be drawn ({shown})."
                                   + (f"\n\n{tbl}" if tbl else ""))
        return "\n\n".join(replacement)

    def fenced(m: re.Match) -> str:
        body = m.group(2).strip()
        if not body.startswith(("{", "[")):
            return m.group(0)
        try:
            json.loads(body)
        except ValueError:
            # Incomplete / broken chart JSON (e.g. a cut-off answer): never shown as raw JSON.
            if re.search(r'"(series|labels|kpis|datasets|chart_type)"\s*:', body):
                problems.append("incomplete chart data")
                return "*(A chart could not be shown: its data was incomplete.)*"
            return m.group(0)
        r = handle(body)
        return m.group(0) if r is None else r

    out = _FENCE.sub(fenced, text)
    # A fence opened and never closed (a cut-off answer) holding chart data.
    m = re.search(r"```[ \t]*(json|chart)?[ \t]*\n(\s*[\[{].*)$", out, re.S | re.I)
    if m and "```" not in m.group(2) and re.search(r'"(series|labels|kpis|datasets|chart_type)"\s*:', m.group(2)):
        problems.append("incomplete chart data")
        out = out[:m.start()] + "*(A chart could not be shown: its data was incomplete.)*"
    # Bare objects: a line that starts with "{" and the JSON that follows it.
    dec = json.JSONDecoder()
    i, pieces = 0, []
    while True:
        j = out.find("{", i)
        if j < 0:
            pieces.append(out[i:])
            break
        line_start = out.rfind("\n", 0, j) + 1
        if out[line_start:j].strip():
            pieces.append(out[i:j + 1]); i = j + 1
            continue
        try:
            obj, end = dec.raw_decode(out, j)
        except ValueError:
            pieces.append(out[i:j + 1]); i = j + 1
            continue
        r = handle(json.dumps(obj)) if isinstance(obj, dict) else None
        pieces.append(out[i:j] + (r if r is not None else out[j:end]))
        i = end
    cleaned = re.sub(r"\n{3,}", "\n\n", "".join(pieces)).strip()
    return cleaned, charts_out, problems
