"""add_oauth_state_initiating_user

Revision ID: v9w3x48y0z16
Revises: u8v2w37x9y15
Create Date: 2026-10-21 02:00:00.000000

Binds each OAuth state token to the authenticated user who started the flow
so the callback can re-verify tenant and user before storing tokens.
Existing (short-lived, ten-minute) states keep NULL and are rejected by the
callback; users simply restart the connection.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v9w3x48y0z16"
down_revision: Union[str, None] = "u8v2w37x9y15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("oauth_states") as batch:
        batch.add_column(sa.Column("initiated_by_user_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_oauth_states_initiated_by_user",
            "users",
            ["initiated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("oauth_states") as batch:
        batch.drop_constraint("fk_oauth_states_initiated_by_user", type_="foreignkey")
        batch.drop_column("initiated_by_user_id")
