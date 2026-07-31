from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from cubicle.config import settings
from cubicle.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


#: Arbitrary but fixed: two processes migrating the same database have to
#: choose the same number for the lock to mean anything.
MIGRATION_LOCK = 0x0CB1C1E


def _run(connection) -> None:
    # Serialise migrations across processes. Two control planes starting at
    # once — a compose recreate racing an installer, or two replicas booting
    # together — would otherwise both see the same head and both try to apply
    # it, and the loser can leave the schema half-built. The second one now
    # waits, then finds nothing to do.
    connection.exec_driver_sql(f"SELECT pg_advisory_lock({MIGRATION_LOCK})")
    try:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.exec_driver_sql(f"SELECT pg_advisory_unlock({MIGRATION_LOCK})")


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
