"""
Tests for Alembic migrations.

Verify that all 15 core tables are created and the migration completes successfully.
"""

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.engine import create_encrypted_engine
from app.db.migrate import upgrade_to_head

NOW = "2026-10-19T00:00:00.000Z"


@pytest.fixture
def engine(tmp_path):
    """Fresh encrypted DB per test, built by the real migration."""
    eng = create_encrypted_engine(os.urandom(32), str(tmp_path / "clinic.db"))
    upgrade_to_head(eng)
    yield eng
    eng.dispose()


def test_migration_creates_all_15_tables(engine):
    """Verify migration created all 15 core tables (excluding FTS5 internals)."""
    inspector = inspect(engine)
    all_tables = set(inspector.get_table_names())

    # Core tables (excluding FTS5 internal tables like chunks_fts_content, etc.)
    expected_core_tables = {
        "users",
        "settings",
        "patients",
        "encounters",
        "problems",
        "medications",
        "allergies",
        "lab_results",
        "vitals",
        "documents",
        "chunks",
        "ai_threads",
        "ai_messages",
        "ai_citations",
        "audit_log",
    }

    assert expected_core_tables.issubset(all_tables), (
        f"Missing core tables: {expected_core_tables - all_tables}"
    )


def test_migration_creates_indexes(engine):
    """Verify migration created key indexes."""
    inspector = inspect(engine)

    # Check indexes on patients table
    patient_indexes = inspector.get_indexes("patients")
    patient_index_names = {idx["name"] for idx in patient_indexes}

    assert "idx_patients_name" in patient_index_names, "Missing idx_patients_name"
    assert "idx_patients_birth" in patient_index_names, "Missing idx_patients_birth"

    # Check indexes on encounters table
    encounter_indexes = inspector.get_indexes("encounters")
    encounter_index_names = {idx["name"] for idx in encounter_indexes}

    assert "idx_enc_patient_date" in encounter_index_names, "Missing idx_enc_patient_date"


def test_fts5_virtual_table_exists(engine):
    """Verify FTS5 virtual table was created."""
    inspector = inspect(engine)
    all_tables = set(inspector.get_table_names())

    assert "chunks_fts" in all_tables, "FTS5 virtual table chunks_fts not created"


def test_audit_log_table_structure(engine):
    """Verify audit_log table has correct structure."""
    inspector = inspect(engine)

    result = inspector.get_columns("audit_log")
    column_names = {col["name"] for col in result}

    assert "audit_no" in column_names
    assert "hash" in column_names
    assert "event_type" in column_names
    assert "created_at" in column_names


def test_migration_version_tracked(engine):
    """Verify Alembic migration version is tracked."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert "alembic_version" in tables, "Alembic migration version table not created"

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
        count = result.scalar()
        assert count >= 1, "Migration version not recorded"


def test_foreign_keys_enforced(engine):
    """Verify FOREIGN KEY constraints are enforced."""
    with engine.connect() as conn:
        # Try to insert encounter with non-existent patient_id
        # All NOT NULL columns supplied, so only the FK can fail
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute(
                text(
                    "INSERT INTO encounters (patient_id, encounter_date, encounter_type, "
                    "created_at, updated_at) "
                    "VALUES (9999, '2026-10-19', 'consult', :now, :now)"
                ),
                {"now": NOW},
            )
            conn.commit()


def test_check_constraints_enforced(engine):
    """Verify CHECK constraints are enforced on sex column."""
    with engine.connect() as conn:
        # Try to insert patient with invalid sex value
        # All NOT NULL columns supplied, so only the sex CHECK can fail
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                text(
                    "INSERT INTO patients (patient_number, last_name, first_name, birth_date, "
                    "sex, created_at, updated_at) "
                    "VALUES ('P001', 'Doe', 'Jane', '1990-01-01', 'INVALID', :now, :now)"
                ),
                {"now": NOW},
            )
            conn.commit()


def test_encounter_type_check_constraint(engine):
    """Verify CHECK constraint on encounter_type."""
    with engine.connect() as conn:
        # This test creates its own patient instead of relying on another test's data
        patient_id = conn.execute(
            text(
                "INSERT INTO patients (patient_number, last_name, first_name, birth_date, "
                "sex, created_at, updated_at) "
                "VALUES ('P001', 'Doe', 'Jane', '1990-01-01', 'female', :now, :now) "
                "RETURNING id"
            ),
            {"now": NOW},
        ).scalar()
        conn.commit()

        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                text(
                    "INSERT INTO encounters (patient_id, encounter_date, encounter_type, "
                    "created_at, updated_at) "
                    "VALUES (:pid, '2026-10-19', 'invalid_type', :now, :now)"
                ),
                {"pid": patient_id, "now": NOW},
            )
            conn.commit()
