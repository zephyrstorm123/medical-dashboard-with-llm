"""
Audit service: append-only event log with a SHA-256 hash chain.

Each entry's hash covers the previous entry's hash, so editing or removing an
old row with an outside tool breaks the chain and verify_chain() reports it.
The DB triggers in migration 001 make the table append-only for our own code.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog

# prev_hash of the very first entry (the column is NOT NULL)
GENESIS_HASH = "0" * 64

ACTIONS = frozenset(
    {
        "unlock",
        "unlock_failed",
        "lock",
        "view",
        "create",
        "update",
        "delete",
        "export",
        "ai_query",
        "backup",
        "restore",
    }
)

# Field names like "birth_date" or "phone"; anything with spaces or capitals is
# probably free text and is rejected.
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _now() -> str:
    """UTC time in the same format as the DB default: 2026-10-20T08:15:30.123Z."""
    now = datetime.now(timezone.utc)
    return f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond // 1000:03d}Z"


def _encode_detail(detail: Optional[dict]) -> Optional[str]:
    """
    Validate detail and return it as canonical JSON.

    Allowed: keys that are field names; values that are int, bool, None, or a
    list of field names (e.g. {"fields": ["phone", "address"]}). Single string
    values are rejected, so clinical text cannot slip into the audit log.
    This is a guard, not a proof: callers must still pass IDs only.

    Raises:
        ValueError: If any key or value is not allowed
    """
    if detail is None:
        return None
    for key, value in detail.items():
        if not isinstance(key, str) or not _FIELD_NAME.match(key):
            raise ValueError(f"detail key {key!r} is not a field name")
        if value is None or isinstance(value, (bool, int)):
            continue
        if isinstance(value, list) and all(
            isinstance(item, str) and _FIELD_NAME.match(item) for item in value
        ):
            continue
        raise ValueError(f"detail[{key!r}] must be an ID, count, flag or list of field names")
    return json.dumps(detail, sort_keys=True, separators=(",", ":"))


def _check_id(name: str, value: Optional[int]) -> None:
    """IDs must be real ints: SQLite would happily store text in an INTEGER column."""
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{name} must be an int or None")


def compute_hash(
    prev_hash: str,
    occurred_at: str,
    user_id: Optional[int],
    action: str,
    entity_type: Optional[str],
    entity_id: Optional[int],
    patient_id: Optional[int],
    detail: Optional[str],
) -> str:
    """
    SHA-256 over the fields listed in docs/05, in that fixed order.

    The fields are JSON-encoded as a list rather than concatenated, so
    ("ab", "c") and ("a", "bc") cannot produce the same hash.
    """
    payload = json.dumps(
        [prev_hash, occurred_at, user_id, action, entity_type, entity_id, patient_id, detail],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_row(row: AuditLog, prev_hash: str) -> str:
    return compute_hash(
        prev_hash,
        row.occurred_at,
        row.user_id,
        row.action,
        row.entity_type,
        row.entity_id,
        row.patient_id,
        row.detail,
    )


class AuditService:
    """Write and verify audit_log entries within the caller's session."""

    def __init__(self, session: Session):
        self.session = session

    def log(
        self,
        action: str,
        *,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        patient_id: Optional[int] = None,
        detail: Optional[dict] = None,
    ) -> int:
        """
        Append one entry and return its id.

        The entry is flushed but not committed: it is saved or rolled back
        together with the change it describes.

        Raises:
            ValueError: If action is unknown, an ID is not an int, or
                entity_type/detail looks like free text
        """
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {sorted(ACTIONS)}")
        for name, value in (
            ("user_id", user_id),
            ("entity_id", entity_id),
            ("patient_id", patient_id),
        ):
            _check_id(name, value)
        if entity_type is not None and not _FIELD_NAME.match(entity_type):
            raise ValueError("entity_type must be a table-style name like 'patient'")

        row = AuditLog(
            occurred_at=_now(),
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            patient_id=patient_id,
            detail=_encode_detail(detail),
            prev_hash=self._last_hash(),
        )
        row.hash = _hash_row(row, row.prev_hash)
        self.session.add(row)
        self.session.flush()
        return row.id

    def _last_hash(self) -> str:
        last = self.session.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
        return last or GENESIS_HASH

    def verify_chain(self) -> list[int]:
        """
        Recompute every hash from the first entry onward.

        Returns:
            ids of entries whose content or link is broken (empty = intact).
            A changed row fails its own hash; a removed row makes the next
            row's prev_hash wrong. Removing the newest rows is not detectable
            from the chain alone.
        """
        broken = []
        expected_prev = GENESIS_HASH
        for row in self.session.scalars(select(AuditLog).order_by(AuditLog.id)):
            if row.prev_hash != expected_prev or _hash_row(row, row.prev_hash) != row.hash:
                broken.append(row.id)
            expected_prev = row.hash
        return broken

    def patient_trail(self, patient_id: int) -> list[AuditLog]:
        """All entries for one patient, oldest first (for review and export)."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.patient_id == patient_id)
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
        return list(self.session.scalars(stmt))
