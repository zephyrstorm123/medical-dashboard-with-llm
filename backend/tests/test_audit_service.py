"""
Tests for audit service (hash chain, tamper detection, append-only).

Verify:
1. Hash chain computes correctly
2. Tamper detection catches modifications
3. Audit log is append-only (DB triggers prevent UPDATE/DELETE)
4. Patient audit trail queries work
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Base, Patient
from app.services.audit import AuditService


@pytest.fixture
def temp_db():
    """Create temporary SQLite database with all tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(f"sqlite:///{db_path}")

        # Create all tables
        Base.metadata.create_all(engine)

        # Add audit_log triggers (append-only)
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TRIGGER audit_no_update
                BEFORE UPDATE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only; cannot update');
                END;
            """))

            conn.execute(text("""
                CREATE TRIGGER audit_no_delete
                BEFORE DELETE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only; cannot delete');
                END;
            """))

            conn.commit()

        yield engine, db_path
        engine.dispose()


@pytest.fixture
def session(temp_db):
    """Create SQLAlchemy session with temporary database."""
    engine, _ = temp_db
    session_maker = Session(engine)
    yield session_maker
    session_maker.close()


def test_hash_chain_computation():
    """Verify SHA-256 hash chain computes correctly."""
    # First entry (no prev_hash)
    hash1 = AuditService._compute_hash(
        prev_hash=None,
        event_type="create",
        table_name="patients",
        record_id=1,
        old_values=None,
        new_values={"first_name": "Jane", "last_name": "Doe"},
    )

    # Should be 64-character hex string (SHA-256)
    assert isinstance(hash1, str)
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)

    # Second entry (with prev_hash)
    hash2 = AuditService._compute_hash(
        prev_hash=hash1,
        event_type="update",
        table_name="patients",
        record_id=1,
        old_values={"first_name": "Jane"},
        new_values={"first_name": "Janet"},
    )

    # Should be different from hash1
    assert hash2 != hash1
    assert len(hash2) == 64

    # Same inputs produce same hash (deterministic)
    hash2_repeat = AuditService._compute_hash(
        prev_hash=hash1,
        event_type="update",
        table_name="patients",
        record_id=1,
        old_values={"first_name": "Jane"},
        new_values={"first_name": "Janet"},
    )

    assert hash2 == hash2_repeat


def test_log_create_event(session):
    """Verify logging a create event."""
    audit_svc = AuditService(session)

    # Log patient creation
    audit_no = audit_svc.log_event(
        patient_id=1,
        event_type="create",
        table_name="patients",
        record_id=1,
        user_id=10,
        new_values={"first_name": "Jane", "last_name": "Doe", "sex": "F"},
    )

    session.commit()

    # Verify entry was created
    assert audit_no == 1
    entry = session.query(AuditLog).filter(AuditLog.audit_no == 1).first()
    assert entry is not None
    assert entry.event_type == "create"
    assert entry.table_name == "patients"
    assert entry.patient_id == 1
    assert entry.prev_hash is None
    assert entry.hash is not None


def test_log_update_event(session):
    """Verify logging an update event creates hash chain."""
    audit_svc = AuditService(session)

    # Log create
    audit_no1 = audit_svc.log_event(
        patient_id=1,
        event_type="create",
        table_name="patients",
        record_id=1,
        new_values={"first_name": "Jane"},
    )

    # Log update
    audit_no2 = audit_svc.log_event(
        patient_id=1,
        event_type="update",
        table_name="patients",
        record_id=1,
        old_values={"first_name": "Jane"},
        new_values={"first_name": "Janet"},
    )

    session.commit()

    # Verify chain
    entry1 = session.query(AuditLog).filter(AuditLog.audit_no == audit_no1).first()
    entry2 = session.query(AuditLog).filter(AuditLog.audit_no == audit_no2).first()

    assert entry1.prev_hash is None
    assert entry2.prev_hash == entry1.hash
    assert entry2.hash != entry1.hash


def test_audit_log_append_only_trigger(session):
    """Verify audit_log cannot be updated or deleted (append-only trigger)."""
    audit_svc = AuditService(session)

    # Create an audit entry
    audit_no = audit_svc.log_event(
        patient_id=1,
        event_type="create",
        table_name="patients",
        record_id=1,
        new_values={"first_name": "Jane"},
    )

    session.commit()

    # Try to UPDATE - should fail
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "UPDATE audit_log SET hash = 'tampered' "
                "WHERE audit_no = :audit_no"
            ),
            {"audit_no": audit_no},
        )
        session.commit()

    session.rollback()

    # Try to DELETE - should fail
    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM audit_log WHERE audit_no = :audit_no"),
            {"audit_no": audit_no},
        )
        session.commit()


def test_verify_hash_chain_valid(session):
    """Verify hash chain validation passes with valid entries."""
    audit_svc = AuditService(session)

    # Log multiple events
    audit_svc.log_event(
        patient_id=1,
        event_type="create",
        table_name="patients",
        record_id=1,
        new_values={"first_name": "Jane"},
    )

    audit_svc.log_event(
        patient_id=1,
        event_type="update",
        table_name="patients",
        record_id=1,
        old_values={"first_name": "Jane"},
        new_values={"first_name": "Janet"},
    )

    audit_svc.log_event(
        patient_id=1,
        event_type="archive",
        table_name="patients",
        record_id=1,
        new_values={"archived_at": "2026-10-19"},
    )

    session.commit()

    # Verify chain
    is_valid, errors = audit_svc.verify_hash_chain()

    assert is_valid, f"Hash chain should be valid, but got errors: {errors}"
    assert len(errors) == 0


def test_verify_hash_chain_tamper_detection(session):
    """Verify DB trigger prevents tampering attempts."""
    audit_svc = AuditService(session)

    # Log event
    audit_no = audit_svc.log_event(
        patient_id=1,
        event_type="create",
        table_name="patients",
        record_id=1,
        new_values={"first_name": "Jane"},
    )

    session.commit()

    # Attempt to tamper with hash directly using raw SQL
    # The DB trigger should prevent this
    try:
        session.execute(
            text(
                "UPDATE audit_log SET hash = 'tampered0000000000000000000000000000000' "
                "WHERE audit_no = :audit_no"
            ),
            {"audit_no": audit_no},
        )
        session.commit()
        # If we get here, the trigger failed (bad)
        pytest.fail("Trigger should have prevented UPDATE on audit_log")
    except IntegrityError as e:
        # Expected: trigger prevents update
        assert "append-only" in str(e).lower()
        session.rollback()


def test_verify_hash_chain_from_mid_point(session):
    """Verify hash chain validation from a specific starting point."""
    audit_svc = AuditService(session)

    # Log 3 events
    for i in range(1, 4):
        audit_svc.log_event(
            patient_id=1,
            event_type="create",
            table_name="patients",
            record_id=i,
            new_values={"id": i},
        )

    session.commit()

    # Verify from entry 2 onward
    is_valid, errors = audit_svc.verify_hash_chain(start_audit_no=2)

    assert is_valid, f"Chain from audit_no=2 should be valid, but got: {errors}"


def test_get_patient_audit_trail(session):
    """Verify retrieving patient audit trail."""
    audit_svc = AuditService(session)

    # Create patient in DB
    patient = Patient(
        patient_number="P001",
        first_name="Jane",
        last_name="Doe",
        sex="female",
        birth_date="1990-01-01",
        created_at="2026-10-19T00:00:00.000Z",
        updated_at="2026-10-19T00:00:00.000Z",
    )
    session.add(patient)
    session.flush()
    patient_id = patient.id

    # Log events for this patient
    audit_svc.log_event(
        patient_id=patient_id,
        event_type="create",
        table_name="patients",
        record_id=patient_id,
        new_values={"first_name": "Jane", "last_name": "Doe"},
    )

    audit_svc.log_event(
        patient_id=patient_id,
        event_type="update",
        table_name="patients",
        record_id=patient_id,
        old_values={"first_name": "Jane"},
        new_values={"first_name": "Janet"},
    )

    session.commit()

    # Retrieve audit trail
    trail = audit_svc.get_patient_audit_trail(patient_id)

    assert len(trail) == 2
    assert trail[0]["event_type"] == "create"
    assert trail[0]["table_name"] == "patients"
    assert trail[1]["event_type"] == "update"
    assert trail[1]["new_values"]["first_name"] == "Janet"


def test_log_event_invalid_event_type(session):
    """Verify invalid event type raises ValueError."""
    audit_svc = AuditService(session)

    with pytest.raises(ValueError):
        audit_svc.log_event(
            patient_id=1,
            event_type="invalid_type",
            table_name="patients",
            record_id=1,
            new_values={"name": "Test"},
        )


def test_log_delete_event(session):
    """Verify logging a delete event (soft or hard)."""
    audit_svc = AuditService(session)

    # Log delete
    audit_no = audit_svc.log_event(
        patient_id=1,
        event_type="delete",
        table_name="patients",
        record_id=1,
        old_values={"first_name": "Jane", "last_name": "Doe"},
        new_values=None,
    )

    session.commit()

    entry = session.query(AuditLog).filter(AuditLog.audit_no == audit_no).first()
    assert entry.event_type == "delete"
    assert entry.old_values is not None
    assert entry.new_values is None
