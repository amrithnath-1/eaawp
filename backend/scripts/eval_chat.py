"""
Ask an EAAWP AI employee a batch of real questions and check every answer automatically.

Runs against a live EAAWP (local or deployed) with the real AI model and your real integrations, so it shows exactly
what a person would see. Nothing is changed: the questions are read-only (no approvals are granted by this script).

Usage (Windows Command Prompt, from the backend folder):
    set EAAWP_API=https://your-backend.onrender.com
    set EAAWP_EMAIL=you@company.com
    set EAAWP_COMPANY_ID=<your company id>
    python scripts\\eval_chat.py                      (asks for the password; it is never printed or saved)
    python scripts\\eval_chat.py --role DIGITAL_MARKETING_MANAGER --site gecservices.in --out eval_report.md

Each answer is flagged when: the request failed, the plan failed, a tool step failed, the answer is a non-answer
("I used these tools…", raw tool names), it refuses work its tools can do, figures appear without any completed data
step, or the expected source is missing. Fix, redeploy, run again until the report is clean.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

NON_ANSWER = re.compile(r"\(I used these tools|\bintegration_[0-9a-f]{6,}_\w+", re.I)
REFUSAL = re.compile(r"outside (of )?my (responsibilit|role|scope)|consult the data analyst|a company administrator "
                     r"can (make|do)", re.I)
FIGURE = re.compile(r"\b\d[\d,]*(\.\d+)?\s*%?")


def scenarios(site: str) -> list[dict]:
    """(prompt, expectations). `follow_up` keeps the same conversation as the previous question."""
    return [
        {"q": "Which websites are connected in Search Console?", "source": "Search Console"},
        {"q": f"What were the clicks, impressions, CTR and average position for {site} in the last 28 days?",
         "source": "Search Console", "numbers": True},
        {"q": f"What are the top 10 search queries for {site} in the last 3 months?", "source": "Search Console",
         "numbers": True},
        {"q": "Which of those has the lowest CTR?", "follow_up": True, "numbers": True},
        {"q": f"Which pages of {site} get the most clicks?", "source": "Search Console", "numbers": True},
        {"q": f"Compare the last 7 days with the 7 days before for {site}.", "source": "Search Console",
         "numbers": True},
        {"q": f"Show the details of {site} in Search Console.", "source": "Search Console"},
        {"q": "What was our CTR in 2019?", "honesty": True},
        {"q": f"Give me 3 SEO recommendations based on our Search Console data for {site}.",
         "source": "Search Console"},
        {"q": "give the list of repositiries in my github", "source": "GitHub"},
        {"q": "What is my company name and what services do we offer?"},
        {"q": f"Read {site} and summarise what the website says we offer.", "source": site},
        {"q": "Who are the main competitors of our business in our area? Use the internet.", "source": "http"},
        {"q": "Draft an Instagram post for our passport service."},
        {"q": "What can you do for me?"},
    ]


def call(api: str, method: str, path: str, token: str | None = None, body: dict | None = None,
         timeout: int = 180) -> tuple[int, dict]:
    req = urllib.request.Request(api.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def check(s: dict, status: int, body: dict) -> list[str]:
    problems: list[str] = []
    if status != 200:
        return [f"HTTP {status}: {str(body.get('detail', ''))[:200]}"]
    msg = body.get("message") or ""
    steps = body.get("step_summaries") or []
    plan = body.get("plan_status")
    if plan == "failed":
        problems.append("plan failed")
    if plan == "awaiting_setup":
        problems.append("stopped for setup (integration / grant / site choice)")
    failed = [x for x in steps if x.endswith("→ failed")]
    if failed:
        problems.append(f"{len(failed)} step(s) failed: " + "; ".join(f[:120] for f in failed))
    if NON_ANSWER.search(msg) and len(msg) < 400:
        problems.append("non-answer (tool note / raw tool name)")
    if REFUSAL.search(msg):
        problems.append("refused or deflected")
    data_steps = [x for x in steps if (x.startswith("[READ]") or "[INTEGRATION]" in x) and x.endswith("→ completed")]
    if s.get("numbers") and FIGURE.search(msg) and not data_steps and not s.get("follow_up"):
        problems.append("figures without any completed data step (possible invention)")
    if s.get("source") and s["source"].lower() not in (msg + " ".join(body.get("sources") or [])).lower():
        problems.append(f"expected source '{s['source']}' not mentioned")
    if s.get("honesty") and FIGURE.search(msg) and not re.search(r"no data|not available|only keeps|16 months|"
                                                                 r"cannot|can't|isn’t|isn't", msg, re.I):
        problems.append("gave figures for a period that has no data")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default="DIGITAL_MARKETING_MANAGER")
    ap.add_argument("--site", default="gecservices.in")
    ap.add_argument("--out", default="eval_report.md")
    ap.add_argument("--only", type=int, nargs="*", help="run only these scenario numbers (1-based)")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between questions (rate limits)")
    a = ap.parse_args()
    api = os.environ.get("EAAWP_API", "http://localhost:8000")
    email, company = os.environ.get("EAAWP_EMAIL"), os.environ.get("EAAWP_COMPANY_ID")
    if not email or not company:
        print("Set EAAWP_EMAIL and EAAWP_COMPANY_ID first (see the top of this file).")
        return 2
    password = os.environ.get("EAAWP_PASSWORD") or getpass.getpass(f"Password for {email}: ")
    st, tok = call(api, "POST", "/api/v1/auth/token", body={"email": email, "password": password,
                                                             "company_id": company})
    password = ""
    if st != 200:
        print(f"Login failed: HTTP {st}")
        return 2
    token = tok["access_token"]
    st, ws = call(api, "PUT", "/api/v1/workspace", token, {"role_key": a.role})
    if st != 200:
        print(f"Could not select {a.role}: HTTP {st} {ws}")
        return 2
    role_name = ((ws.get("ai") or {}).get("role_name")) or a.role.replace("_", " ").title()

    lines = [f"# EAAWP chat evaluation — {a.role} — {time.strftime('%Y-%m-%d %H:%M')}", ""]
    conv, bad = None, 0
    for i, s in enumerate(scenarios(a.site), 1):
        if a.only and i not in a.only:
            continue
        body = {"blueprint": {"agent_id": "eval", "role_name": role_name, "role_key": a.role, "system_persona": "-",
                              "allowed_tools": [], "guarded_tools": [], "tenant_id": company},
                "user_prompt": s["q"]}
        if s.get("follow_up") and conv:
            body["conversation_id"] = conv
        t0 = time.time()
        st, out = call(api, "POST", "/api/v1/agent/execute", token, body)
        secs = time.time() - t0
        conv = out.get("conversation_id") or conv
        problems = check(s, st, out)
        bad += bool(problems)
        mark = "FAIL" if problems else "PASS"
        print(f"{i:2}. {mark} ({secs:4.1f}s) {s['q']}" + (f"\n      → {'; '.join(problems)}" if problems else ""))
        lines += [f"## {i}. {mark} — {s['q']}", f"*{secs:.1f}s · plan: {out.get('plan_status')}*", ""]
        if problems:
            lines += ["**Problems:** " + "; ".join(problems), ""]
        lines += ["**Steps:**", *[f"- {x}" for x in out.get("step_summaries") or ["(none)"]], "",
                  "**Answer:**", "", (out.get("message") or str(out.get("detail", "")))[:3000], ""]
        time.sleep(a.pause)
    lines.insert(1, f"**{bad} of {len([1 for i in range(len(scenarios(a.site))) if not a.only or i + 1 in a.only])} "
                    f"answers flagged.**")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n{bad} flagged. Full report: {os.path.abspath(a.out)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
