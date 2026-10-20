"""Test SQLAlchemy models definition and relationships."""

import os
import tempfile

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import create_encrypted_engine
from app.db.models import Base, Encounter, Patient


def test_models_create_all_tables():
    """Test that all 15 models can be created in a database."""
    data_key = b"0" * 32

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_encrypted_engine(data_key, db_path)

        # Create all tables from models
        Base.metadata.create_all(engine)

        # Verify all expected tables exist
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = [row[0] for row in result.fetchall()]

        # Expected 15 tables + sqlite_sequence (for autoincrement)
        expected_tables = {
            "ai_citations",
            "ai_messages",
            "ai_threads",
            "allergies",
            "audit_log",
            "chunks",
            "documents",
            "encounters",
            "lab_results",
            "medications",
            "patients",
            "problems",
            "settings",
            "users",
            "vitals",
        }

        assert expected_tables.issubset(set(tables)), (
            f"Missing tables: {expected_tables - set(tables)}"
        )

        engine.dispose()


def test_patient_with_relationships():
    """Test that a patient can be created with related encounters."""
    data_key = b"1" * 32

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_encrypted_engine(data_key, db_path)

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # Create a patient
            patient = Patient(
                patient_number="CHT-001",
                last_name="Dela Cruz",
                first_name="Juan",
                birth_date="1980-05-15",
                sex="male",
            )
            session.add(patient)
            session.flush()  # Get the patient ID

            # Create an encounter for that patient
            encounter = Encounter(
                patient_id=patient.id,
                encounter_date="2026-10-17",
                encounter_type="consult",
                chief_complaint="Headache",
                subjective="Patient reports 2-day headache",
                objective="BP 120/80, HR 72",
                assessment="Migraine vs tension headache",
                plan="Prescribe ibuprofen, follow up in 1 week",
            )
            session.add(encounter)
            session.commit()

            # Verify relationships work
            assert len(patient.encounters) == 1
            assert patient.encounters[0].chief_complaint == "Headache"
            assert patient.encounters[0].patient_id == patient.id

        engine.dispose()


def test_foreign_key_constraint_enforced():
    """Test that foreign key constraints are enforced."""
    data_key = b"2" * 32

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_encrypted_engine(data_key, db_path)

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # Try to create an encounter with non-existent patient_id
            encounter = Encounter(
                patient_id=999,  # This patient doesn't exist
                encounter_date="2026-10-17",
                encounter_type="consult",
            )
            session.add(encounter)

            try:
                session.commit()
                raise AssertionError("Expected IntegrityError for invalid foreign key")
            except IntegrityError:
                pass  # Expected

        engine.dispose()


def test_check_constraints_enforced():
    """Test that CHECK constraints are enforced at the database level."""
    data_key = b"3" * 32

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_encrypted_engine(data_key, db_path)

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # Try to create a patient with invalid sex
            patient = Patient(
                patient_number="CHT-BAD",
                last_name="Test",
                first_name="Patient",
                birth_date="2000-01-01",
                sex="invalid_sex",  # Not in ('female','male','other','unknown')
            )
            session.add(patient)

            try:
                session.commit()
                raise AssertionError("Expected IntegrityError for invalid CHECK constraint")
            except IntegrityError:
                pass  # Expected

        engine.dispose()
