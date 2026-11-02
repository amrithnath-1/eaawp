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

import re
import uuid
from typing import Any

from app.services.grounding import ungrounded_figures

TYPES = ("bar", "line", "area", "pie", "donut", "scatter", "kpi", "table")
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
    return "bar"


def build(raw: dict, evidence: str) -> tuple[dict | None, str]:
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
        "labels": labels, "series": series, "kpis": kpis,
        "source": str(raw.get("source") or "Data returned by the tools used in this answer")[:200],
        "note": (str(raw.get("note"))[:300] if raw.get("note") else None),
    }, ""
