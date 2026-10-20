"""Regenerate docs/route_auth_inventory.md from the live route table."""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "inventory-only-" + "x" * 32)

from app.core.route_inventory import build_inventory, render_markdown  # noqa: E402
from app.main import app  # noqa: E402

out = ROOT / "docs" / "route_auth_inventory.md"
out.write_text(render_markdown(build_inventory(app)), encoding="utf-8")
print(f"wrote {out}")
