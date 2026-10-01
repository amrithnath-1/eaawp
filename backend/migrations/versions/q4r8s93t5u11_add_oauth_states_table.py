"""add_oauth_states_table

Revision ID: q4r8s93t5u11
Revises: p3q7r82s4t10
Create Date: 2026-09-22 11:00:00.000000

Adds oauth_states table for Phase 4 Google Search Console OAuth2 CSRF protection.

The table stores short-lived, one-time-use state tokens that bind an OAuth2
authorization request to a specific (tenant_id, integration_id) context.
State tokens expire after 10 minutes and are consumed on first successful use.

No credential data is stored here — tokens go to integration_catalog.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q4r8s93t5u11"
down_revision: Union[str, None] = "p3q7r82s4t10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state_token", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integration_catalog.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_token", name="uq_oauth_states_state_token"),
    )
    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_oauth_states_state_token"),
            ["state_token"], unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_oauth_states_tenant_id"),
            ["tenant_id"], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_oauth_states_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_oauth_states_state_token"))
    op.drop_table("oauth_states")
