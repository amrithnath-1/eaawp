"""add_module_activations

Revision ID: a0b4c59d1e67
Revises: f9a3b48c0d56
Create Date: 2026-10-22 08:00:00.000000

Per-company module activation (Phase L). Additive only. A company with no row for a module uses the catalog default,
so existing companies keep every module they have today.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a0b4c59d1e67"
down_revision: Union[str, None] = "f9a3b48c0d56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "module_activations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("changed_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "module_key", name="uq_module_activation"),
    )
    op.create_index("ix_module_activations_tenant_id", "module_activations", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_module_activations_tenant_id", table_name="module_activations")
    op.drop_table("module_activations")
