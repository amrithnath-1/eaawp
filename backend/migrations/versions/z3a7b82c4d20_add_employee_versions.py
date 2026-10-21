"""add_employee_versions

Revision ID: z3a7b82c4d20
Revises: y2z6a71b3c19
Create Date: 2026-10-21 20:00:00.000000

Versioned AI employee configuration with approval and rollback. Additive only (one new table).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z3a7b82c4d20"
down_revision: Union[str, None] = "y2z6a71b3c19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "employee_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ai_employee_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_employee_id"], ["ai_employees.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("ai_employee_id", "version", name="uq_employee_version"),
    )
    op.create_index("ix_employee_versions_tenant_id", "employee_versions", ["tenant_id"])
    op.create_index("ix_employee_versions_ai_employee_id", "employee_versions", ["ai_employee_id"])
    op.create_index("ix_employee_versions_tenant_employee", "employee_versions", ["tenant_id", "ai_employee_id"])


def downgrade() -> None:
    op.drop_table("employee_versions")
