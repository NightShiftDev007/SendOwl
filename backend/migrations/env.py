"""Alembic runtime bound to the validated application database setting."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.companies import models as company_models
from app.config import load_runtime_settings
from app.database import ApplicationBase, normalize_async_database_url
from app.media import models as media_models
from app.scenarios import models as scenario_models
from app.simulations import models as simulation_models
from app.world_models import models as world_model_models

del company_models, media_models, scenario_models, simulation_models, world_model_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ApplicationBase.metadata


def required_database_url() -> str:
    """Return the configured async database URL or fail before migration work."""
    settings = load_runtime_settings(os.environ)
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required to run database migrations")
    return normalize_async_database_url(settings.database_url)


def run_migrations_offline() -> None:
    """Render migrations without opening a database connection."""
    context.configure(
        url=required_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    """Configure Alembic on one synchronous connection facade."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open one async engine and execute migrations transactionally."""
    engine = create_async_engine(required_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
