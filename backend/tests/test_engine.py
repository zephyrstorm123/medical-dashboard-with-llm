"""Test database engine creation and SQLCipher integration."""

import os
import sqlite3
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.db.engine import create_encrypted_engine


def test_create_encrypted_engine_with_valid_key():
    """Test that create_encrypted_engine returns a working SQLAlchemy engine."""
    data_key = b"0" * 32  # 32-byte key for AES-256

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        engine = create_encrypted_engine(data_key, db_path)
        assert engine is not None

        # Verify we can connect and execute a basic query
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 AS test"))
            row = result.fetchone()
            assert row[0] == 1

        # Dispose of the engine to close all connections
        engine.dispose()


def test_create_encrypted_engine_rejects_invalid_key_length():
    """Test that create_encrypted_engine rejects keys that are not exactly 32 bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        # Too short
        with pytest.raises(ValueError, match="Data key must be 32 bytes long"):
            create_encrypted_engine(b"short_key", db_path)

        # Too long
        with pytest.raises(ValueError, match="Data key must be 32 bytes long"):
            create_encrypted_engine(b"x" * 33, db_path)


def test_wal_mode_enabled():
    """Test that every connection runs in WAL journal mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        engine = create_encrypted_engine(b"A" * 32, db_path)
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        engine.dispose()

        assert mode == "wal"


def test_database_file_is_unreadable_without_key():
    """Phase 1 exit check: plain sqlite3 cannot read the file, and no plaintext is on disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        engine = create_encrypted_engine(os.urandom(32), db_path)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (x TEXT)"))
            conn.execute(text("INSERT INTO t VALUES ('Juan Dela Cruz')"))
        engine.dispose()

        with open(db_path, "rb") as f:
            raw = f.read()
        assert not raw.startswith(b"SQLite format 3")
        assert b"Juan Dela Cruz" not in raw

        plain = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                plain.execute("SELECT * FROM t").fetchall()
        finally:
            plain.close()


def test_wrong_key_cannot_open_database():
    """A different 32-byte key is rejected on connect."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        engine = create_encrypted_engine(os.urandom(32), db_path)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (x TEXT)"))
        engine.dispose()

        wrong = create_encrypted_engine(os.urandom(32), db_path)
        with pytest.raises(DatabaseError):
            with wrong.connect():
                pass
        wrong.dispose()


def test_foreign_keys_are_enforced():
    """Test that foreign key constraints are enabled."""
    data_key = b"B" * 32

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        engine = create_encrypted_engine(data_key, db_path)
        with engine.connect() as conn:
            # Create parent and child tables with FK constraint
            conn.execute(
                text("""
                CREATE TABLE parent (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES parent(id)
                )
            """)
            )
            conn.commit()

            # Try to insert a child with non-existent parent (should fail)
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO child (parent_id) VALUES (999)"))
                conn.commit()

        engine.dispose()
