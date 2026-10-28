"""
Grounding check: every figure the AI states about integration data must be
traceable to what the integration actually returned.

The model writes the prose; this module decides whether the prose may be
shown.  A figure counts as grounded when it appears in the tool evidence (or
in the user's own request), allowing for rounding and for rates shown as
percentages.  Small whole numbers (0-10) are exempt - they are counts of
things in the sentence ("3 channels", "top 5"), not reported data.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(%?)")


def _parse(token: str) -> tuple[float, int]:
    clean = token.replace(",", "")
    decimals = len(clean.split(".")[1]) if "." in clean else 0
    return float(clean), decimals


def evidence_values(text: str) -> list[float]:
    vals: list[float] = []
    for m in _NUM.finditer(text or ""):
        v, _ = _parse(m.group(1))
        vals.append(v)
        if 0 < v < 1:           # a rate such as 0.4412 may be reported as 44%
            vals.append(v * 100)
    return vals


_FIELD = re.compile(r'"(\w+)"\s*:\s*(-?\d+(?:\.\d+)?)')


def _derived(evidence: str, pool: list[float]) -> list[float]:
    """Figures an answer may legitimately compute from the data: column totals (e.g. total clicks over the rows),
    and differences, ratios and percentage changes between two returned values (e.g. "up 12% on last week")."""
    cols: dict[str, float] = {}
    counts: dict[str, int] = {}
    for key, num in _FIELD.findall(evidence or ""):
        cols[key] = cols.get(key, 0.0) + float(num)
        counts[key] = counts.get(key, 0) + 1
    out = [v for k, v in cols.items() if counts[k] > 1]
    out += [cols[k] / counts[k] for k in cols if counts[k] > 1]                           # averages
    small = list(dict.fromkeys(pool + out))[:150]
    for a in small:
        for b in small:
            if a == b:
                continue
            out += [a + b, a - b]
            if b:
                out += [a / b, a / b * 100, (a - b) / b * 100]
    return out


def ungrounded_figures(answer: str, evidence: str) -> list[str]:
    """Figures in ``answer`` that cannot be found in, or computed from, ``evidence``."""
    pool = evidence_values(evidence)
    derived: list[float] | None = None
    bad: list[str] = []
    for m in _NUM.finditer(answer or ""):
        raw, pct = m.group(1), m.group(2)
        v, decimals = _parse(raw)
        if not pct and decimals == 0 and v <= 10:
            continue
        if any(round(e, decimals) == v or abs(e - v) < 1e-9 for e in pool):
            continue
        if derived is None:
            derived = _derived(evidence, pool)
        if any(round(abs(e), decimals) == v for e in derived):
            continue
        bad.append(raw + pct)
    return bad
