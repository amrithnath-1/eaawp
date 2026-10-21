"""add_blocked_columns

Revision ID: f9a3b48c0d56
Revises: e8f2a37b9c45
Create Date: 2026-10-22 06:00:00.000000

Column-level protection for connected databases (Phase K). Additive only; existing rows get an empty list.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a3b48c0d56"
down_revision: Union[str, None] = "e8f2a37b9c45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schema_entities", sa.Column("blocked_columns_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("schema_entities") as b:
        b.drop_column("blocked_columns_json")
