"""
Understanding requests to change EAAWP itself, in plain words.

People do not know tool names. "Add Passport Services to our services", "call yourself Mira", "make priya@x.com a
manager", "pause the clerk" or "require approval before emails go out" are all changes to EAAWP's own settings. Only
an administrator can make them, and the exact change is always shown for approval before anything is saved.

- looks_like_settings_change(): a high-precision check (no model call) that a message asks to change EAAWP settings.
  For administrators the request then goes straight to the customization planner instead of relying on the chat
  model to pick the right tool.
- asker_block(): tells the model who it is talking to and whether that person can change settings, so it never tells
  an administrator to "ask an administrator".
- is_refusal(): answers that only say "that's not my job" are not worth remembering. Stored refusals would be fed
  back as memory and make the model refuse the same request again.
"""
from __future__ import annotations

import re

_QUESTION = re.compile(r"^\s*(how|where|why|what|when|which|who|explain|tell me how|can you explain|is it possible)\b",
                       re.I)
_VERB = (r"(add|remove|delete|drop|change|update|edit|set|rename|call|name|make|enable|disable|turn\s+(on|off)|"
         r"switch\s+(on|off)|pause|resume|unpause|activate|deactivate|reactivate|grant|revoke|give|allow|invite|"
         r"promote|demote|require|configure|customi[sz]e|replace|include|put|correct|fix|create|schedule|build|"
         r"set\s+up|stop)")
_TARGETS = [
    # Company profile
    r"\b(company|business|approved|our|the)\s+profile\b",
    r"\btag\s?line\b", r"\bbrand\s+name\b", r"\babout\s+(us|section)\b", r"\bslogan\b",
    r"\b(to|from|in|into|on)\s+(our|the|my)\s+(company'?s?\s+)?(services|service\s+list|list\s+of\s+services)\b",
    r"\bservice(s)?\s+(called|named)\b",
    r"\b(our|the\s+company'?s?)\s+(website|web\s+address|location|service\s+area|target\s+audiences?|"
    r"forbidden\s+claims|approved\s+claims|brand\s+voice|policies)\b",
    # An AI employee's own settings
    r"\b(call|name|rename)\s+(yourself|you|it|the\s+[\w\s]{0,30}?(assistant|employee|manager|agent|clerk|analyst))\b",
    r"\b(your|its)\s+(name|default\s+tone|tone\s+of\s+voice|communication\s+style|instructions|quick\s+prompts|"
    r"responsibilities|duties)\b",
    r"\b(assistant|employee|manager|agent|clerk|analyst)'?s?\s+(name|tone|communication\s+style|instructions|"
    r"quick\s+prompts|responsibilities)\b",
    r"\bfrom\s+now\s+on\b.*\b(always|never)\b",
    r"\b(pause|resume|unpause)\s+(the\s+)?[\w\s]{0,30}?(assistant|employee|manager|agent|clerk|analyst|yourself)\b",
    # Marketplace, team, access, integrations, workflows, approvals, notifications
    r"\b(marketplace|module)\b",
    r"\b(team\s+member|invite|invitation)\b",
    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b.*\b(manager|admin|administrator|employee|role)\b",
    r"\b(access|permission)\s+(to|for)\b", r"\bcapabilit(y|ies)\b",
    r"\b(switch|turn)\s+(off|on)\s+[\w\s]{0,20}?(integration|connection|search\s+console|analytics|github|database|"
    r"mcp|email)\b",
    r"\bworkflows?\b",
    r"\bapproval\s+(rule|policy|policies|setting)s?\b", r"\b(require|requires|need|needs)\s+(an?\s+)?approval\b",
    r"\bnotification\s+emails?\b",
    r"\b(eaawp|platform|workspace)\s+settings?\b", r"\bin\s+(the\s+)?settings\b",
]
_TARGET_RE = re.compile("|".join(f"(?:{t})" for t in _TARGETS), re.I | re.S)
_VERB_RE = re.compile(rf"\b{_VERB}\b", re.I)
_EXPLICIT = re.compile(r"\b(customi[sz]e\s+eaawp|customize_eaawp|eaawp\s+settings)\b", re.I)


def looks_like_settings_change(text: str) -> bool:
    """True when the message asks to change EAAWP's own settings (not a question about how to)."""
    t = (text or "").strip()
    if not t or len(t) > 4000:
        return False
    if _EXPLICIT.search(t):
        return True
    if _QUESTION.search(t) and not re.match(r"^\s*(can|could|would|will)\s+you\b", t, re.I):
        return False
    return bool(_VERB_RE.search(t) and _TARGET_RE.search(t))


def asker_block(name: str, account_role: str, is_admin: bool, can_customize: bool) -> str:
    who = f"{name or 'A team member'} ({account_role or 'Employee'})"
    if is_admin and can_customize:
        return (
            "## Who you are talking to\n"
            f"{who}, a company ADMINISTRATOR of EAAWP. They may change EAAWP's own settings through you: the company "
            "profile, AI employee settings, pausing AI employees, Marketplace modules, team members, access grants, "
            "connected services, workflows, approval rules and notification emails. When they ask for such a change, "
            "propose it with the customize_eaawp tool (they approve it before anything is saved). Never tell them to "
            "ask an administrator: they are one. Changing settings is not outside your role."
        )
    return (
        "## Who you are talking to\n"
        f"{who}. They are not an administrator. If they ask to change EAAWP's own settings (company profile, AI "
        "employee settings, team, integrations, workflows, approval rules), say that a company administrator (Company "
        "Admin or AI Administrator) can make that change by asking any AI employee, and help with their real work."
    )


_REFUSAL = re.compile(
    r"(outside (of )?my (responsibilit|role|scope|remit)|not (part of|within) my (role|responsibilit|job|scope)|"
    r"falls outside|beyond my (role|scope)|i (can(no|')t|am not able to|'m not able to) (help|do|make|change) (with )?th(is|at)|"
    r"(a|your) company administrator can|ask (a|your) (company )?administrator|platform administration task)",
    re.I,
)


def is_refusal(answer: str) -> bool:
    """A short answer that mainly declines (\"that is outside my responsibilities ... an administrator can\")."""
    a = (answer or "").strip()
    return bool(a) and len(a) < 900 and bool(_REFUSAL.search(a))
