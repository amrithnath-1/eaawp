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


_ROW = re.compile(r"\{[^{}]*\}")
_FIELD = re.compile(r'"(\w+)"\s*:\s*(-?\d+(?:\.\d+)?)')
# Integration rows as the tools print them: "  3. query: x | clicks: 2 | impressions: 1156 | ctr: 0.0017"
_PIPE_ROW = re.compile(r"^\s*\d+\.\s+(.*\|.*)$", re.M)
_PIPE_FIELD = re.compile(r"(?:^|\|)\s*(\w+):\s*(-?\d+(?:\.\d+)?)\s*(?=\||$)")


def _rows(evidence: str) -> list[list[tuple[str, str]]]:
    """Every data row in the evidence, JSON objects and pipe rows alike, as (field, number) pairs."""
    rows = [_FIELD.findall(obj) for obj in _ROW.findall(evidence or "")[:500]]
    rows += [_PIPE_FIELD.findall(m.group(1)) for m in _PIPE_ROW.finditer(evidence or "")][:500]
    return [r for r in rows if r]


def _derived(evidence: str) -> tuple[list[float], list[float]]:
    """(plain figures, percentages) an answer may legitimately compute from the data. Only like with like:
    totals, averages and differences within one measure (e.g. clicks), % change and share within one measure, and
    ratios between measure totals (overall CTR = total clicks / total impressions). Never arbitrary pairs, which would
    let almost any small number pass."""
    cols: dict[str, list[float]] = {}
    for row in _rows(evidence):
        for key, num in row:
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
    # Ratios between two measures of the SAME row (e.g. one page's clicks / impressions = that page's CTR).
    for row in _rows(evidence):
        nums = [float(n) for _, n in row][:12]
        for a in nums:
            for b in nums:
                if a != b and b:
                    pct.append(a / b * 100)
                    plain.append(a / b)
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


# ── Checking an answer sentence by sentence ──────────────────────────────────
#
# The old rule replaced the WHOLE answer when one figure could not be traced, so an analysis with one target in it
# ("aim for 50 clicks") came back as a raw data dump. Now each sentence (or table row / bullet) is checked on its own:
#   * figures traced to the data (or computed from it), or to the company's own documents → kept;
#   * targets, estimates and projections (worded as such: "aim for", "could", "estimate", "up to"…) → kept and
#     marked "(estimate)" so they are never mistaken for measured results;
#   * general guidance with a unit ("titles under 60 characters", "within 2 weeks") and years → kept;
#   * a sentence stating an untraceable figure as fact → left out, and the answer says how many were left out.
# Only when most of the factual content is unsupported is the answer replaced by the data itself, as readable tables.

from dataclasses import dataclass, field as _field

_ESTIMATE = re.compile(
    r"\b(target|targets|aim|aiming|goal|goals|estimate[sd]?|estimated|estimation|could|might|may|potential(?:ly)?|"
    r"project(?:ed|ion)s?|forecast|expect(?:ed)?|would|up to|approximately|roughly|around|about|if you|if the|"
    r"by improving|by raising|possible|opportunity to|plan to|should reach|can reach|benchmark|typical(?:ly)?|"
    r"industry average|best practice)\b", re.I)
_GUIDANCE_UNIT = re.compile(
    r"^\s*(?:-\s*\d+\s*)?(characters?|chars?|words?|days?|weeks?|months?|years?|hours?|minutes?|seconds?|steps?|"
    r"times?|kb|mb|px|pixels?|links?|headings?|images?|questions?|faqs?|sections?|paragraphs?|sentences?|lines?)\b",
    re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(*\[A-Z0-9])")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")


@dataclass
class Verified:
    text: str
    removed: list[str] = _field(default_factory=list)       # sentences left out (their unsupported figures)
    estimates: int = 0                                       # sentences kept as marked estimates
    replaced: bool = False                                   # True: the data is shown instead of the prose
    factual_units: int = 0


_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _bad_in(unit: str, evidence: str) -> list[str]:
    # A specific date must be one the data covers (a wrong period makes every figure next to it wrong).
    bad = [d for d in _DATE.findall(unit) if d not in (evidence or "")]
    for fig in ungrounded_figures(unit, evidence):
        # where is it in the sentence?
        i = unit.find(fig)
        after = unit[i + len(fig):] if i >= 0 else ""
        num = fig.rstrip("%").replace(",", "")
        try:
            v = float(num)
        except ValueError:
            v = -1
        if not fig.endswith("%") and 1900 <= v <= 2100 and "." not in num:
            continue                                         # a year
        if not fig.endswith("%") and _GUIDANCE_UNIT.match(after):
            continue                                         # guidance, not reported data
        bad.append(fig)
    return bad


def _mark_estimate(unit: str) -> str:
    if re.search(r"estimate", unit, re.I):
        return unit
    stripped = unit.rstrip()
    m = re.search(r"([.!?]*)$", stripped)
    end = m.group(1) if m else ""
    return stripped[:len(stripped) - len(end)] + " *(estimate)*" + end


def verify_answer(answer: str, evidence: str) -> Verified:
    """Keep what the data supports, mark estimates, leave out unsupported factual statements (see above)."""
    out_lines: list[str] = []
    v = Verified(text=answer)
    if not answer:
        return v
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped or _TABLE_SEP.match(stripped) or stripped.startswith(("#", "```")):
            out_lines.append(line)
            continue
        if stripped.startswith("|"):                          # a table row is one unit
            bad = _bad_in(stripped, evidence)
            if bad:
                v.factual_units += 1
                v.removed.append(stripped)
                continue
            if _NUM.search(stripped):
                v.factual_units += 1
            out_lines.append(line)
            continue
        prefix = line[:len(line) - len(line.lstrip())]
        m = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)", line)
        if m:
            prefix, body = m.group(1), line[m.end():]
        else:
            body = line.strip()
        kept = []
        for sent in _SPLIT.split(body):
            if not sent.strip():
                continue
            bad = _bad_in(sent, evidence)
            if _NUM.search(sent):
                v.factual_units += 1
            if not bad:
                kept.append(sent)
            elif _ESTIMATE.search(sent):
                kept.append(_mark_estimate(sent))
                v.estimates += 1
            else:
                v.removed.append(sent.strip())
        if kept:
            out_lines.append(prefix + " ".join(kept))
    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Headings left with nothing under them are dropped.
    text = re.sub(r"(?m)^#{1,6} [^\n]*\n+(?=#{1,6} |\Z)", "", text).strip()
    v.text = text
    prose = re.sub(r"[#*_`|>\-\s]", "", text)
    if v.removed and (len(prose) < 80 or len(v.removed) > max(2, v.factual_units * 0.5)):
        v.replaced = True
    return v
