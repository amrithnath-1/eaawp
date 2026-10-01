"""add_role_configurations

Revision ID: a3f2c8e91d04
Revises: 8137a1d51bcf
Create Date: 2026-09-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f2c8e91d04"
down_revision: Union[str, None] = "8137a1d51bcf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("agent_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("responsibilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("objectives_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("system_persona", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("permissions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("workflows_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("monitoring_rules_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("communication_style", sa.String(length=64), nullable=False, server_default="Concise"),
        sa.Column("schedule_preferences_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("memory_settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("llm_model", sa.String(length=128), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("autonomy_level", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("quick_prompts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "role_key", name="uq_role_config_tenant_role"),
    )
    with op.batch_alter_table("role_configurations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_role_configurations_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_role_configurations_role_key"), ["role_key"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("role_configurations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_role_configurations_role_key"))
        batch_op.drop_index(batch_op.f("ix_role_configurations_tenant_id"))
    op.drop_table("role_configurations")
