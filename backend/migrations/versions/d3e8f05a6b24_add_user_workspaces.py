"""add_user_workspaces

Revision ID: d3e8f05a6b24
Revises: c2d6e7f83a19
Create Date: 2026-10-22 14:00:00.000000

Post-registration AI role selection. Additive: one row per user holding the AI employee workspace they selected.

Existing accounts: every active user of a company that has not deactivated the Digital Marketing Manager module gets
that workspace (the only experience the app offered before), marked source='migration_default', so nobody is pushed
into a selection loop and they can switch at any time. Users of companies that turned the module off get no row and
choose on their next sign-in. Downgrade drops only the new table.
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e8f05a6b24"
down_revision: Union[str, None] = "c2d6e7f83a19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT = "DIGITAL_MARKETING_MANAGER"


def upgrade() -> None:
    table = op.create_table(
        "user_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_key", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="user"),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_user_workspace_user"),
    )
    op.create_index("ix_user_workspaces_tenant_id", "user_workspaces", ["tenant_id"])

    conn = op.get_bind()
    disabled = {r[0] for r in conn.execute(sa.text(
        "SELECT tenant_id FROM module_activations WHERE module_key = :k AND active = :off"), {"k": _DEFAULT, "off": False})}
    users = conn.execute(sa.text("SELECT id, tenant_id FROM users WHERE is_active = :on"), {"on": True}).fetchall()
    rows = [{"id": str(uuid.uuid4()), "tenant_id": tid, "user_id": uid, "role_key": _DEFAULT, "source": "migration_default"}
            for uid, tid in users if tid not in disabled]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index("ix_user_workspaces_tenant_id", table_name="user_workspaces")
    op.drop_table("user_workspaces")
