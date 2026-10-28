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


def _derived(evidence: str) -> tuple[list[float], list[float]]:
    """(plain figures, percentages) an answer may legitimately compute from the data. Only like with like:
    totals, averages and differences within one measure (e.g. clicks), % change and share within one measure, and
    ratios between measure totals (overall CTR = total clicks / total impressions). Never arbitrary pairs, which would
    let almost any small number pass."""
    cols: dict[str, list[float]] = {}
    for key, num in _FIELD.findall(evidence or ""):
        cols.setdefault(key, []).append(float(num))
    plain: list[float] = []
    pct: list[float] = []
    totals = {k: sum(v) for k, v in cols.items() if len(v) > 1}
    for k, vals in cols.items():
        if len(vals) > 1:
            plain += [totals[k], totals[k] / len(vals)]
        for a in vals[:60]:
            for b in vals[:60]:
                if a == b:
                    continue
                plain += [a - b, a + b]
                if b:
                    pct += [(a - b) / b * 100, a / b * 100]
                if totals.get(k):
                    pct.append(a / totals[k] * 100)
    for ka, ta in totals.items():
        for kb, tb in totals.items():
            if ka != kb and tb:
                pct.append(ta / tb * 100)
                plain.append(ta / tb)
    return plain, pct


def ungrounded_figures(answer: str, evidence: str) -> list[str]:
    """Figures in ``answer`` that cannot be found in, or computed from, ``evidence``."""
    pool = evidence_values(evidence)
    derived: tuple[list[float], list[float]] | None = None
    bad: list[str] = []
    for m in _NUM.finditer(answer or ""):
        raw, pct = m.group(1), m.group(2)
        v, decimals = _parse(raw)
        if not pct and decimals == 0 and v <= 10:
            continue
        if any(round(e, decimals) == v or abs(e - v) < 1e-9 for e in pool):
            continue
        if derived is None:
            derived = _derived(evidence)
        if any(round(abs(e), decimals) == v for e in (derived[1] if pct else derived[0])):
            continue
        bad.append(raw + pct)
    return bad
