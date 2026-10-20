"""
Tests for the audit service (docs/05 audit_log, Phase 1 exit check).

Verify:
1. Entries chain from GENESIS_HASH and verify as intact
2. Editing or removing a row with an outside tool is detected
3. audit_log is append-only (DB triggers block UPDATE/DELETE)
4. detail rejects free text; patient_id has no FK
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.db.models import AuditLog
from app.services.audit import GENESIS_HASH, AuditService, compute_hash


def _drop_append_only_triggers(engine):
    """Simulate an outside tool that has the key and removes our triggers."""
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER audit_no_update"))
        conn.execute(text("DROP TRIGGER audit_no_delete"))


def test_first_entry_links_to_genesis_and_chain_verifies(session):
    audit = AuditService(session)
    first = audit.log("unlock", user_id=None)
    second = audit.log("view", entity_type="patient", entity_id=1, patient_id=1)
    session.commit()

    rows = {r.id: r for r in session.query(AuditLog)}
    assert rows[first].prev_hash == GENESIS_HASH
    assert rows[second].prev_hash == rows[first].hash
    assert audit.verify_chain() == []


def test_hash_covers_every_doc05_field():
    base = ["0" * 64, "2026-10-20T00:00:00.000Z", 1, "view", "patient", 5, 5, None]
    original = compute_hash(*base)
    assert len(original) == 64
    assert compute_hash(*base) == original  # deterministic
    for i in range(len(base)):
        changed = list(base)
        changed[i] = "changed" if not isinstance(base[i], int) else base[i] + 1
        assert compute_hash(*changed) != original, f"field {i} not covered by hash"


def test_edited_row_is_detected(engine, session):
    audit = AuditService(session)
    ids = [audit.log("view", patient_id=1, entity_type="patient", entity_id=1) for _ in range(3)]
    session.commit()

    _drop_append_only_triggers(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit_log SET patient_id = 2 WHERE id = :id"), {"id": ids[1]})

    session.expire_all()
    assert audit.verify_chain() == [ids[1]]


def test_edited_row_with_recomputed_hash_breaks_next_link(engine, session):
    audit = AuditService(session)
    ids = [audit.log("view", patient_id=1) for _ in range(3)]
    session.commit()

    # Attacker changes row 2 and recomputes its own hash to match
    row = session.get(AuditLog, ids[1])
    forged = compute_hash(
        row.prev_hash, row.occurred_at, row.user_id, "export", None, None, 1, None
    )
    _drop_append_only_triggers(engine)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE audit_log SET action = 'export', hash = :h WHERE id = :id"),
            {"h": forged, "id": ids[1]},
        )

    session.expire_all()
    assert audit.verify_chain() == [ids[2]]


def test_removed_row_is_detected(engine, session):
    audit = AuditService(session)
    ids = [audit.log("view", patient_id=1) for _ in range(3)]
    session.commit()

    _drop_append_only_triggers(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": ids[1]})

    session.expire_all()
    assert audit.verify_chain() == [ids[2]]


def test_update_blocked_by_trigger(engine, session):
    AuditService(session).log("lock")
    session.commit()
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE audit_log SET action = 'unlock'"))


def test_delete_blocked_by_trigger(engine, session):
    AuditService(session).log("lock")
    session.commit()
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log"))


def test_unknown_action_rejected(session):
    with pytest.raises(ValueError, match="action"):
        AuditService(session).log("archive")


def test_db_check_rejects_unknown_action(engine):
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_log (occurred_at, action, prev_hash, hash) "
                    "VALUES ('2026-10-20T00:00:00.000Z', 'archive', :g, 'x')"
                ),
                {"g": GENESIS_HASH},
            )


@pytest.mark.parametrize(
    "detail",
    [
        {"note": "patient reports chest pain"},  # free-text value
        {"Chief Complaint": 1},  # key is not a field name
        {"fields": ["chest pain"]},  # list item is not a field name
        {"temperature": 38.5},  # floats could be clinical values
    ],
)
def test_detail_rejects_free_text(session, detail):
    with pytest.raises(ValueError, match="detail"):
        AuditService(session).log("update", detail=detail)


def test_detail_accepts_ids_and_field_names(session):
    audit = AuditService(session)
    entry_id = audit.log(
        "update",
        entity_type="patient",
        entity_id=7,
        patient_id=7,
        detail={"fields": ["phone", "address"], "count": 2, "restored": False},
    )
    session.commit()
    stored = session.get(AuditLog, entry_id).detail
    assert stored == '{"count":2,"fields":["phone","address"],"restored":false}'
    assert audit.verify_chain() == []


def test_patient_id_has_no_foreign_key(session):
    # Patient 9999 does not exist; the entry must still be written
    AuditService(session).log("view", patient_id=9999)
    session.commit()


def test_patient_trail_returns_only_that_patient(session):
    audit = AuditService(session)
    audit.log("view", patient_id=1)
    audit.log("view", patient_id=2)
    audit.log("update", patient_id=1, detail={"fields": ["phone"]})
    session.commit()

    trail = audit.patient_trail(1)
    assert [r.action for r in trail] == ["view", "update"]
    assert all(r.patient_id == 1 for r in trail)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"patient_id": "Juan Dela Cruz"},
        {"entity_id": "chest pain"},
        {"user_id": "1"},
        {"patient_id": True},
        {"entity_type": "patient record of Juan"},
    ],
)
def test_ids_and_entity_type_reject_free_text(session, kwargs):
    with pytest.raises(ValueError):
        AuditService(session).log("view", **kwargs)


def test_db_default_occurred_at_matches_app_format(engine):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO audit_log (action, prev_hash, hash) VALUES ('lock', :g, 'h1')"),
            {"g": GENESIS_HASH},
        )
        value = conn.execute(text("SELECT occurred_at FROM audit_log")).scalar()
    assert len(value) == 24 and value.endswith("Z")


def test_db_rejects_duplicate_hash(engine):
    insert = text("INSERT INTO audit_log (action, prev_hash, hash) VALUES ('lock', :g, 'same')")
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        with engine.begin() as conn:
            conn.execute(insert, {"g": GENESIS_HASH})
            conn.execute(insert, {"g": GENESIS_HASH})
