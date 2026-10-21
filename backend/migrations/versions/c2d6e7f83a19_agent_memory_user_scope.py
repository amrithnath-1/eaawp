"""agent_memory_user_scope

Revision ID: c2d6e7f83a19
Revises: b1c5d6e72f08
Create Date: 2026-10-22 10:00:00.000000

Phase M (agent memory). Additive: agent_memories.user_id (NULL = company-wide curated note). Existing automatic
history rows keep user_id NULL and are therefore never retrieved (their author is unknown).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d6e7f83a19"
down_revision: Union[str, None] = "b1c5d6e72f08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_memories", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("agent_memories") as batch:
        batch.drop_index("ix_agent_memories_user_id")
        batch.drop_column("user_id")
