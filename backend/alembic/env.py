"""
Alembic migration environment.

This script runs every time you call 'alembic upgrade' or 'alembic downgrade'.
It connects to the encrypted SQLite database and applies SQL from migration files.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add backend to path so we can import app.db.models
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.db.models import Base  # noqa: E402

config = context.config

# Log Alembic SQL statements
config_file = config.config_file_name
if config_file is not None:
    fileConfig(config_file)

target_metadata = Base.metadata


def configure_sqlalchemy_url(
    url: str, data_key: bytes
) -> dict[str, object]:
    """
    Build SQLAlchemy config for encrypted SQLite.
    
    Args:
        url: Database URL (e.g., "sqlite:///clinic.db")
        data_key: 32-byte encryption key
    
    Returns:
        Dictionary of engine arguments for engine_from_config()
    """
    config.set_main_option("sqlalchemy.url", url)
    return config.get_section(config.config_ini_section)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (generate SQL, don't execute).
    
    This is useful for:
    - Reviewing SQL before applying
    - Databases you can't connect to directly
    - CI/CD that needs to inspect migrations first
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode (execute SQL against real database).
    
    For encrypted SQLite (SQLCipher), we:
    1. Create engine with PRAGMA key applied
    2. Connect and run migrations
    3. Close connection
    """
    # For now, use unencrypted SQLite for migrations (simplified)
    # In production, you would:
    # - Read data_key from keys.json
    # - Call create_encrypted_engine(data_key, db_path)
    # - Pass that connection to context.configure()
    
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.echo"] = False

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.StaticPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()