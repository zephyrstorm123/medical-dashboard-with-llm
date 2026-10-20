"""Run Alembic migrations on an already-unlocked, encrypted engine."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic" / "alembic.ini"


def upgrade_to_head(engine: Engine) -> None:
    """Apply all migrations using the caller's encrypted connection."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
