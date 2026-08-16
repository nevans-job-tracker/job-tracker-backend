"""Alembic environment.

The database URL comes from the application's own `Settings` rather than a
second copy in `alembic.ini`. That keeps one source of truth for connection
details, and it means the `DATABASE_URL` override the test suite relies on
works here too — pointing Alembic at a throwaway SQLite file is just setting
that variable, exactly as `tests/conftest.py` does.
"""
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

from app.config import settings
from app.database import Base

# Imported for its side effect: defining the models registers them on
# Base.metadata, which is what autogenerate compares against. Without this
# import the metadata is empty and autogenerate would propose dropping every
# table it finds.
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it, for review or manual apply."""
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = settings.sqlalchemy_url

    # Built directly rather than via engine_from_config, which would read the
    # URL back out of the ini file. ConfigParser treats '%' as interpolation
    # syntax, so a password containing one would corrupt the URL on the way
    # through.
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place. Batch mode rewrites the
            # table instead, so a future migration still applies when the URL
            # points at SQLite — which is how the tests run.
            render_as_batch=_is_sqlite(url),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
