"""
Deterministic safety boundary for the Medical Assistant. This runs BEFORE any language model and does not depend on one.

  emergency  -> immediate "get emergency help now" message (no LLM, no booking talk)
  crisis     -> supportive message directing to emergency services / a crisis line
  boundary   -> the assistant does not diagnose, prescribe or give dosing/treatment advice; offers appointment + clinic info

The patterns are intentionally broad (a false alarm costs one sentence; a miss could cost much more). They are a safety net
for a clinic-support assistant, NOT a clinical triage tool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY_MESSAGE = (
    "This could be a medical emergency. Please call your local emergency number now (for example 911, 112 or 999) "
    "or go to the nearest emergency department. Do not wait for an appointment or for a reply here."
)
CRISIS_MESSAGE = (
    "I'm really sorry you are going through this, and I'm glad you said something. You deserve support right now. "
    "If you might act on these thoughts or are in immediate danger, please call your local emergency number. "
    "You can also reach a crisis line in your country (in the US, call or text 988). If you can, tell someone near you "
    "how you are feeling. I can also help you request an urgent appointment with the clinic."
)
BOUNDARY_MESSAGE = (
    "I can't give medical advice, diagnose conditions, or advise on medicines and doses - a clinician needs to do that. "
    "I can help you request an appointment, check clinic information, or prepare what to tell the clinician."
)
DISCLAIMER = "This assistant supports clinic administration only. It does not give medical advice, diagnoses or treatment."

_EMERGENCY = re.compile(
    r"chest (pain|pressure|tightness)|pain in (my )?chest|heart attack|"
    r"(can'?t|cannot|unable to|struggling to|difficulty|trouble) (breathe|breathing)|shortness of breath|gasping|"
    r"(face|facial) (is )?droop|slurred speech|sudden(ly)? (numb|weak|confus)|one side of (my|the) (body|face)|stroke|"
    r"(severe|heavy|uncontrol\w*|won'?t stop|not stopping) bleeding|bleeding (heavily|a lot|won'?t stop)|"
    r"unconscious|passed out|not responding|unresponsive|seizure|convulsing|"
    r"overdos|poison|swallowed (bleach|pills|battery)|"
    r"anaphyla|throat (is )?(swelling|closing)|swollen (tongue|throat)|"
    r"severe allergic",
    re.IGNORECASE)
_CRISIS = re.compile(
    r"suicid|kill myself|end (my|it all|my own) life|want to die|better off dead|hurt myself|harm myself|self[- ]harm|"
    r"don'?t want to (live|be alive)",
    re.IGNORECASE)
_ADVICE = re.compile(
    r"\bwhat (dose|dosage)\b|how (much|many) (\w+ ){0,3}(should|can) i (take|use|give)|\bshould i (take|stop|skip|increase|double|reduce)\b|"
    r"\bcan i (take|mix|combine)\b|\bis it safe to (take|mix|combine)\b|"
    r"\bdiagnos\w*|\bdo i have\b|\bis (this|it) (cancer|serious|an infection|diabetes)\b|what('?s| is) (wrong with me|causing)|"
    r"\bprescri\w*|\bwhich (antibiotic|medicine|medication|drug|pill|tablet)\b|\bstop taking my\b|\bmedical advice\b|\btreat(ment)? for my\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Guard:
    kind: str          # emergency | crisis | boundary
    message: str


def emergency_flags(text: str) -> list[str]:
    """Phrases in ``text`` that look like an emergency or crisis (used to flag appointment requests)."""
    return list(dict.fromkeys(m.group(0).lower() for m in [*_EMERGENCY.finditer(text or ""), *_CRISIS.finditer(text or "")]))[:6]


def screen(text: str) -> Guard | None:
    t = text or ""
    if _CRISIS.search(t):
        return Guard("crisis", CRISIS_MESSAGE)
    if _EMERGENCY.search(t):
        return Guard("emergency", EMERGENCY_MESSAGE)
    if _ADVICE.search(t):
        return Guard("boundary", BOUNDARY_MESSAGE)
    return None
