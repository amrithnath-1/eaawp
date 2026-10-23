"""Alembic migration environment — async SQLAlchemy."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make sure `app` package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import normalize_database_url  # noqa: E402
from app.db.models import Base  # noqa: E402
import app.db.monitoring_models  # noqa: E402, F401
import app.db.email_models  # noqa: E402, F401
import app.db.email_draft_models  # noqa: E402, F401
import app.db.campaign_models  # noqa: E402, F401
import app.db.strategy_models  # noqa: E402, F401
import app.db.content_models  # noqa: E402, F401
import app.db.memory_models  # noqa: E402, F401
import app.db.notification_models  # noqa: E402, F401
import app.db.channel_models  # noqa: E402, F401
import app.db.integration_models  # noqa: E402, F401  ← Phase 2 integration framework
import app.db.oauth_models  # noqa: E402, F401  ← Phase 4 OAuth state management
import app.db.provider_config_models  # noqa: E402, F401  ← Admin-Assisted Config Engine
import app.db.pending_task_models  # noqa: E402, F401  ← requests waiting for integration setup
import app.db.workflow_run_models  # noqa: E402, F401  ← workflow run history
import app.db.meeting_models  # noqa: E402, F401  ← Meeting Room
import app.db.employee_version_models  # noqa: E402, F401  ← AI employee versions
import app.db.dataset_models  # noqa: E402, F401  ← datasets and analysis reports
import app.db.clerk_models  # noqa: E402, F401  ← Institutional Clerk
import app.db.medical_models  # noqa: E402, F401  ← Medical Assistant (clinic support)
import app.db.invitation_models  # noqa: E402, F401  ← Team invitations
import app.db.module_models  # noqa: E402, F401  ← Marketplace module activation
import app.db.message_models  # noqa: E402, F401  ← Internal messaging
import app.db.workspace_models  # noqa: E402, F401  ← selected AI employee workspace per user
# Phase H/I — new tables for employee builder and workflow engine
# (These are defined in models.py so Base already knows them — no extra import needed)
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with DATABASE_URL env var if set
db_url = normalize_database_url(os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
