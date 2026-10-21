"""
Route-by-route authentication inventory.

Introspects the real FastAPI route table and classifies every endpoint by how
it authenticates, so no route can be added without an explicit decision.

Used by:
  * tests/security/test_route_auth_inventory.py  (fails on any unclassified route)
  * scripts/route_auth_inventory.py              (regenerates docs/route_auth_inventory.md)
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

# Dependencies that prove identity from a verified JWT.
JWT_DEPENDENCIES = {"get_current_user", "get_current_tenant_id", "require_admin"}

# Every endpoint that is intentionally reachable WITHOUT a Bearer token.
# Adding to this list is a security decision: write the reason.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/health"): "Liveness probe; returns no tenant data.",
    ("POST", "/api/v1/auth/token"): "Login: exchanges credentials for tokens.",
    ("POST", "/api/v1/auth/token/form"): "Login (OAuth2 password form variant).",
    ("POST", "/api/v1/auth/refresh"): "Exchanges a valid, unrevoked refresh token (validated in the DB).",
    ("POST", "/api/v1/auth/logout"): "Revokes the presented refresh token.",
    ("POST", "/api/v1/onboarding/company"): "Self-service company registration (creates a new tenant + its admin).",
    ("POST", "/api/v1/team/invitations/lookup"): "Invitee has no account yet; gated by a 256-bit secret single-use token (stored only as SHA-256), rate-limited, one generic error for every invalid state.",
    ("POST", "/api/v1/team/invitations/accept"): "Invitee creates their account with the secret invitation token; expires in 7 days, single-use, rate-limited, generic error when invalid.",
    ("GET", "/api/v1/oauth/google/callback"): (
        "Browser redirect from Google; cannot carry a Bearer token. Protected by a "
        "single-use, expiring state token bound to the initiating user and tenant."
    ),
}


# Mutating (non-GET) endpoints that ORDINARY employees may call.  Everything else
# that changes state must carry ``require_admin``.  Adding here is a security
# decision: write the reason.  tests/security/test_rbac.py enforces this list.
_DAILY = "Day-to-day marketing work for the caller's own tenant; no credentials, access control or configuration."
MEMBER_MUTATIONS: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/agent/execute"): "Core use of the AI employee; tenant forced from the JWT, permissions enforced per capability grant.",
    ("POST", "/api/v1/agent/pending-tasks/{task_id}/resume"): "Re-runs the caller's OWN saved request (admins: any in their company) once setup is complete; same permissions as /agent/execute.",
    ("POST", "/api/v1/meetings"): "Starts a multi-agent session as the caller; every agent runs through /agent/execute's governed pipeline with the caller's permissions and the role's grants.",
    ("POST", "/api/v1/meetings/{meeting_id}/messages"): "Adds work to the caller's OWN meeting (admins: any in their company); same pipeline and permissions as /agent/execute.",
    ("POST", "/api/v1/meetings/{meeting_id}/cancel"): "Stops the caller's own meeting (admins: any in their company) and rejects its pending approval; reduces what runs.",
    ("POST", "/api/v1/meetings/{meeting_id}/resume"): "Continues the caller's own paused meeting after an approval/setup was decided by an admin; cannot approve anything itself.",
    ("POST", "/api/v1/datasets/{dataset_id}/analyze"): "Read-only computation over a non-restricted dataset of the caller's own company (restricted ones are 404 for members); nothing is stored.",
    ("POST", "/api/v1/analysis-reports"): "Saves a report for the caller: the spec is re-run server-side on a dataset the caller may read; stores only engine output; capped per company.",
    ("POST", "/api/v1/clinic/appointments"): "A member requests an appointment AS THEMSELVES (patient forced from the JWT); the safety screen runs on the reason; capped at 10 open requests per person.",
    ("POST", "/api/v1/clinic/appointments/{appointment_id}/notes"): "Patient messages on their OWN appointment (staff: any in their company); internal notes refused for non-staff; closed appointments refused.",
    ("POST", "/api/v1/clinic/appointments/{appointment_id}/cancel"): "Patient cancels their OWN still-open request; reduces what is scheduled and cannot confirm anything.",
    ("POST", "/api/v1/messages/with/{user_id}"): "Any member messages another ACTIVE member of their own company; the sender is forced from the JWT; 2000-char cap; no admin visibility into conversations.",
    ("POST", "/api/v1/clinic/screen"): "Pure function on the submitted text (deterministic safety screen); reads and writes nothing.",
    ("DELETE", "/api/v1/analysis-reports/{report_id}"): "Author deletes their OWN report (admins: any in their company); others get 403/404.",
    ("POST", "/api/v1/clerk/requests"): "Any member files a request AS THEMSELVES (requester forced from the JWT); inputs validated and capped at 25 open requests per person.",
    ("POST", "/api/v1/clerk/requests/{request_id}/comments"): "Requester comments on their OWN request (admins: any in their company); internal notes are refused for non-admins; closed requests are refused.",
    ("POST", "/api/v1/clerk/requests/{request_id}/cancel"): "Requester cancels their OWN still-open request; reduces what is processed and cannot approve anything.",
    ("POST", "/api/v1/agent/pending-tasks/{task_id}/cancel"): "Drops the caller's own waiting request; reduces, never expands, what runs.",
    ("POST", "/api/v1/roles/{role_key}/validate"): "Dry-run validation; persists nothing.",
    ("POST", "/api/v1/knowledge/retrieve"): "Read-only semantic search (POST for the body).",
    ("POST", "/api/v1/data/query"): "Read-only query through admin-defined mappings and entity permissions; audited.",
    ("POST", "/api/v1/tasks"): _DAILY,
    ("PATCH", "/api/v1/tasks/{task_id}"): _DAILY,
    ("POST", "/api/v1/insights/{insight_id}/dismiss"): _DAILY,
    ("POST", "/api/v1/email/drafts/{draft_id}/cancel"): "Cancels a pending draft; reduces, never expands, outbound email.",
    ("POST", "/api/v1/campaigns"): _DAILY,
    ("PATCH", "/api/v1/campaigns/{campaign_id}"): _DAILY,
    ("DELETE", "/api/v1/campaigns/{campaign_id}"): "Archives (soft-deletes) a campaign of the caller's tenant.",
    ("POST", "/api/v1/campaigns/{campaign_id}/metrics"): _DAILY,
    ("POST", "/api/v1/performance/compare"): "Read-only analysis.",
    ("POST", "/api/v1/funnel/analyze"): "Read-only analysis.",
    ("POST", "/api/v1/funnel/campaign/{campaign_id}"): "Read-only analysis.",
    ("POST", "/api/v1/strategy/objectives"): _DAILY,
    ("PATCH", "/api/v1/strategy/objectives/{obj_id}"): _DAILY,
    ("POST", "/api/v1/strategy/analyze"): "Read-only analysis.",
    ("POST", "/api/v1/content"): _DAILY,
    ("PATCH", "/api/v1/content/{content_id}"): _DAILY,
    ("POST", "/api/v1/content/generate/brief"): _DAILY,
    ("POST", "/api/v1/content/generate/ideas"): _DAILY,
    ("POST", "/api/v1/content/generate/draft"): _DAILY,
    ("POST", "/api/v1/content/generate/variants"): _DAILY,
    ("POST", "/api/v1/content/analyze"): "Read-only analysis.",
    ("POST", "/api/v1/memory"): _DAILY,
    ("POST", "/api/v1/notifications/{notification_id}/read"): "Marks the caller's OWN notification read (other people's rows are 404).",
    ("POST", "/api/v1/notifications/read-all"): "Marks only the caller's own notifications read.",
    ("PUT", "/api/v1/notifications/preferences"): "A person's own notification choices (admin-only categories are refused for employees).",
    ("POST", "/api/v1/nl-integration/parse"): "Intent classification only; takes no action.",
    ("POST", "/api/v1/nl-integration/chat"): "Conversation reply only; takes no action.",
    ("POST", "/api/v1/auth/logout/all"): "Revokes the caller's own refresh tokens.",
}


@dataclass(frozen=True)
class RouteAuth:
    method: str
    path: str
    module: str
    classification: str  # JWT | PUBLIC | UNPROTECTED | HEADER_TENANT
    reason: str = ""
    access: str = "-"  # ADMIN | MEMBER (JWT routes) | - (public)


def _walk(dep: Dependant) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    headers: set[str] = {(h.alias or h.name).lower() for h in dep.header_params}
    for sub in dep.dependencies:
        call = sub.call
        if call is not None:
            names.add(getattr(call, "__name__", type(call).__name__))
        n, h = _walk(sub)
        names |= n
        headers |= h
    return names, headers


def build_inventory(app: FastAPI) -> list[RouteAuth]:
    rows: list[RouteAuth] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        names, headers = _walk(route.dependant)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            module = route.endpoint.__module__.rsplit(".", 1)[-1]
            public_reason = PUBLIC_ROUTES.get((method, route.path))
            if "x-tenant-id" in headers:
                cls, reason = "HEADER_TENANT", "Reads X-Tenant-ID as identity."
            elif names & JWT_DEPENDENCIES:
                cls, reason = "JWT", ""
            elif public_reason:
                cls, reason = "PUBLIC", public_reason
            else:
                cls, reason = "UNPROTECTED", "No authentication dependency and not on the public allowlist."
            access = "-" if cls != "JWT" else ("ADMIN" if "require_admin" in names else "MEMBER")
            rows.append(RouteAuth(method, route.path, module, cls, reason, access))
    return sorted(rows, key=lambda r: (r.path, r.method))


def render_markdown(rows: list[RouteAuth]) -> str:
    jwt_rows = [r for r in rows if r.classification == "JWT"]
    public_rows = [r for r in rows if r.classification == "PUBLIC"]
    out = [
        "# Route authentication inventory",
        "",
        "Generated by `python scripts/route_auth_inventory.py` from the live FastAPI route table.",
        "`tests/security/test_route_auth_inventory.py` fails if this file is stale or if any route",
        "is neither JWT-protected nor on the documented public allowlist.",
        "",
        f"- JWT-protected endpoints: **{len(jwt_rows)}**",
        f"- Intentionally public endpoints: **{len(public_rows)}**",
        f"- Admin-only (JWT-protected) endpoints: **{len([r for r in jwt_rows if r.access == 'ADMIN'])}**",
        "",
        "## Intentionally public",
        "",
        "| Method | Path | Why it is public |",
        "| --- | --- | --- |",
    ]
    out += [f"| {r.method} | `{r.path}` | {r.reason} |" for r in public_rows]
    out += ["", "## JWT-protected (tenant and user come from the verified token)", "",
            "| Method | Path | Router module | Role needed |", "| --- | --- | --- | --- |"]
    out += [f"| {r.method} | `{r.path}` | {r.module} | {'Admin' if r.access == 'ADMIN' else 'Any signed-in user'} |" for r in jwt_rows]
    out.append("")
    return "\n".join(out)
