"""
Column-level protection for connected company databases (Phase K).

Allowing a table for AI access used to expose EVERY column. Now columns whose names look sensitive are blocked by default
at discovery time, and an administrator can block or unblock any column. Blocked columns can be neither selected, filtered
on, nor sorted on (filtering/sorting would leak the value by inference), and "all columns" excludes them.
"""
from __future__ import annotations

import json
import re

_SENSITIVE = re.compile(
    r"pass(word|wd|phrase)?|pwd|secret|token|api[_-]?key|private[_-]?key|credential|salt|hash|otp|pin\b|"
    r"ssn|social[_-]?security|national[_-]?id|aadhaar|aadhar|\bpan\b|passport|tax[_-]?id|"
    r"card[_-]?(no|num|number)?|credit|cvv|cvc|iban|account[_-]?(no|num|number)|routing|swift|"
    r"dob|birth|salary|payroll|medical|diagnos|health",
    re.IGNORECASE,
)


def looks_sensitive(name: str) -> bool:
    return bool(_SENSITIVE.search(name or ""))


def suggest_blocked(column_names: list[str]) -> list[str]:
    return [c for c in column_names if looks_sensitive(c)]


def load_blocked(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def dump_blocked(names: list[str]) -> str:
    return json.dumps(sorted(set(names)))
