"""Shared fixtures: a fresh encrypted DB built by the real migration."""

import os

import pytest
from sqlalchemy.orm import Session

from app.db.engine import create_encrypted_engine
from app.db.migrate import upgrade_to_head


@pytest.fixture
def engine(tmp_path):
    """Fresh encrypted DB per test, built by the real migration."""
    eng = create_encrypted_engine(os.urandom(32), str(tmp_path / "clinic.db"))
    upgrade_to_head(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """ORM session on the encrypted test DB."""
    with Session(engine) as s:
        yield s
