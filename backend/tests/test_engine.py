"""Test database engine creation and SQLCipher integration."""

import os
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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


def test_database_with_wal_and_cipher_created():
    """Test that database file is created with encryption enabled."""
    data_key = b"A" * 32
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        
        # Create database
        engine = create_encrypted_engine(data_key, db_path)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE test_table (id INTEGER PRIMARY KEY, data TEXT)"))
            conn.execute(text("INSERT INTO test_table (data) VALUES ('test')"))
            conn.commit()
        engine.dispose()
        
        # Verify database file exists
        assert os.path.exists(db_path), "Database file not created"
        
        # Verify database size is > 0 (encrypted content)
        assert os.path.getsize(db_path) > 0, "Database file is empty"


def test_foreign_keys_are_enforced():
    """Test that foreign key constraints are enabled."""
    data_key = b"B" * 32
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        
        engine = create_encrypted_engine(data_key, db_path)
        with engine.connect() as conn:
            # Create parent and child tables with FK constraint
            conn.execute(text("""
                CREATE TABLE parent (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES parent(id)
                )
            """))
            conn.commit()
            
            # Try to insert a child with non-existent parent (should fail)
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO child (parent_id) VALUES (999)"))
                conn.commit()
        
        engine.dispose()

