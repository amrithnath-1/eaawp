"""
Route-by-route authentication inventory guard.

Any route that is not JWT-protected must be on the explicit PUBLIC_ROUTES
allowlist (with a reason).  A new endpoint therefore cannot ship
unauthenticated by accident.
"""
from __future__ import annotations

import pathlib
import re

from app.core.route_inventory import PUBLIC_ROUTES, build_inventory, render_markdown
from app.main import app

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def test_every_route_is_jwt_protected_or_explicitly_public():
    bad = [r for r in build_inventory(app) if r.classification not in ("JWT", "PUBLIC")]
    assert not bad, "Unprotected routes:\n" + "\n".join(
        f"  {r.method} {r.path} [{r.module}] -> {r.classification}: {r.reason}" for r in bad
    )


def test_no_route_trusts_x_tenant_id_header():
    bad = [r for r in build_inventory(app) if r.classification == "HEADER_TENANT"]
    assert not bad, [f"{r.method} {r.path}" for r in bad]


def test_public_allowlist_has_no_stale_entries():
    live = {(r.method, r.path) for r in build_inventory(app)}
    stale = set(PUBLIC_ROUTES) - live
    assert not stale, f"PUBLIC_ROUTES entries that match no route: {sorted(stale)}"


def test_public_allowlist_entries_are_actually_unauthenticated():
    jwt_public = [r for r in build_inventory(app)
                  if (r.method, r.path) in PUBLIC_ROUTES and r.classification == "JWT"]
    assert not jwt_public, "Allowlisted as public but protected (remove from allowlist): " + str(
        [(r.method, r.path) for r in jwt_public]
    )


def test_inventory_document_is_up_to_date():
    doc = (BACKEND / "docs" / "route_auth_inventory.md").read_text(encoding="utf-8")
    assert doc == render_markdown(build_inventory(app)), (
        "docs/route_auth_inventory.md is stale - run: python scripts/route_auth_inventory.py"
    )


def test_source_never_reads_x_tenant_id_as_identity():
    """No application module may accept X-Tenant-ID as a Header parameter."""
    offenders = []
    for py in (BACKEND / "app").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if re.search(r'Header\([^)]*alias\s*=\s*["\']X-Tenant-ID["\']', text, re.I):
            offenders.append(str(py.relative_to(BACKEND)))
    assert not offenders, offenders


def test_optional_tenant_dependency_is_gone():
    from app.core import auth

    assert not hasattr(auth, "get_optional_tenant_id")
