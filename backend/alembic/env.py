"""
Alembic migration environment.

Online migrations run only on a connection the app has already unlocked with the
data key (see app.db.migrate.upgrade_to_head). Plain `alembic upgrade` from the
command line refuses to run, so it can never create an unencrypted database.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Add backend to path so we can import app.db.models
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.db.models import Base  # noqa: E402

config = context.config

# Only set up logging when run from the command line; when called from the app,
# fileConfig would replace the app's own logging configuration.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate the migration SQL without connecting (for reviewing it)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations on the unlocked, encrypted connection passed in by the app."""
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "Migrations need an unlocked, encrypted connection. "
            "Run them through app.db.migrate.upgrade_to_head(engine)."
        )
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
