"""add_appointments

Revision ID: c6d0e15f7a23
Revises: b5c9d04e6f22
Create Date: 2026-10-21 23:00:00.000000

Medical Assistant (clinic support): appointment requests. Additive only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6d0e15f7a23"
down_revision: Union[str, None] = "b5c9d04e6f22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("patient_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("patient_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("contact", sa.String(120), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("preferred_time", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="requested"),
        sa.Column("scheduled_for", sa.String(25), nullable=True),
        sa.Column("clinician_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("red_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("red_flags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("intake_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("notes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_appointments_tenant_id", "appointments", ["tenant_id"])
    op.create_index("ix_appointments_tenant_status", "appointments", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("appointments")
