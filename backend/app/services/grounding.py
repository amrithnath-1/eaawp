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


def ungrounded_figures(answer: str, evidence: str) -> list[str]:
    """Figures in ``answer`` that cannot be found in ``evidence``."""
    pool = evidence_values(evidence)
    bad: list[str] = []
    for m in _NUM.finditer(answer or ""):
        raw, pct = m.group(1), m.group(2)
        v, decimals = _parse(raw)
        if not pct and decimals == 0 and v <= 10:
            continue
        if any(round(e, decimals) == v or abs(e - v) < 1e-9 for e in pool):
            continue
        bad.append(raw + pct)
    return bad
