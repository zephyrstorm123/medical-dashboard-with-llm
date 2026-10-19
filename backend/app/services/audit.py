"""
Audit service for immutable change tracking with tamper detection.

Every change to patient records is logged with a hash chain that prevents
tampering. The audit_log table is append-only (enforced by DB triggers).
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import AuditLog


class AuditService:
    """Log and verify immutable audit trail with hash chain integrity."""

    def __init__(self, session: Session):
        """
        Initialize audit service.

        Args:
            session: SQLAlchemy session for database access
        """
        self.session = session

    @staticmethod
    def _compute_hash(
        prev_hash: Optional[str],
        event_type: str,
        table_name: str,
        record_id: int,
        old_values: Optional[dict],
        new_values: Optional[dict],
    ) -> str:
        """
        Compute SHA-256 hash for audit log entry.

        Hash includes previous hash (chain) + all event details.
        This allows detection of any tampering: modifying, inserting, or
        deleting audit_log rows would break the chain.

        Args:
            prev_hash: Previous audit entry's hash (or None for first entry)
            event_type: 'create', 'update', 'delete', or 'archive'
            table_name: Name of table that changed (e.g., 'patients')
            record_id: Primary key of changed record
            old_values: Field values before change (None for create)
            new_values: Field values after change (None for delete/archive)

        Returns:
            SHA-256 hash as hex string (64 chars)
        """
        # Build hashable string from all components
        hash_input = {
            "prev_hash": prev_hash,
            "event_type": event_type,
            "table_name": table_name,
            "record_id": record_id,
            "old_values": old_values,
            "new_values": new_values,
        }

        # Serialize to JSON (sorted for consistency)
        hash_string = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))

        # Compute SHA-256
        return hashlib.sha256(hash_string.encode()).hexdigest()

    def log_event(
        self,
        patient_id: Optional[int],
        event_type: str,
        table_name: str,
        record_id: int,
        user_id: Optional[int] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
    ) -> int:
        """
        Log a change event to the audit trail.

        This creates an immutable audit_log entry with hash chain.
        DB triggers enforce append-only (no UPDATE/DELETE allowed).

        Args:
            patient_id: ID of patient whose data changed (None for non-patient events)
            event_type: 'create', 'update', 'delete', or 'archive'
            table_name: Name of table that changed
            record_id: Primary key of changed record
            user_id: ID of clinician who made the change (optional)
            old_values: Field values before change (dict or None)
            new_values: Field values after change (dict or None)

        Returns:
            audit_no: Sequential audit log number (for citation)

        Raises:
            ValueError: If event_type is invalid
        """
        valid_event_types = {"create", "update", "delete", "archive"}
        if event_type not in valid_event_types:
            raise ValueError(f"event_type must be one of {valid_event_types}")

        # Get previous hash (from most recent audit entry)
        prev_hash = self._get_last_hash()

        # Compute this entry's hash
        current_hash = self._compute_hash(
            prev_hash=prev_hash,
            event_type=event_type,
            table_name=table_name,
            record_id=record_id,
            old_values=old_values,
            new_values=new_values,
        )

        # Create audit log entry
        audit_entry = AuditLog(
            patient_id=patient_id,
            event_type=event_type,
            table_name=table_name,
            record_id=record_id,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps(new_values) if new_values else None,
            user_id=user_id,
            prev_hash=prev_hash,
            hash=current_hash,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )

        self.session.add(audit_entry)
        self.session.flush()  # Get audit_no before commit

        audit_no = audit_entry.audit_no
        return audit_no

    def _get_last_hash(self) -> Optional[str]:
        """
        Get the hash of the most recent audit log entry.

        Returns:
            Previous hash (hex string) or None if audit_log is empty
        """
        last_entry = (
            self.session.query(AuditLog)
            .order_by(AuditLog.audit_no.desc())
            .first()
        )
        return last_entry.hash if last_entry else None

    def verify_hash_chain(self, start_audit_no: int = 1) -> tuple[bool, list[str]]:
        """
        Verify integrity of audit hash chain.

        Recomputes all hashes from start_audit_no onward and checks they match
        stored hashes. Any mismatch indicates tampering.

        Args:
            start_audit_no: First audit entry to check (default: 1 = from beginning)

        Returns:
            (is_valid, errors) where:
            - is_valid: True if all hashes are valid (no tampering detected)
            - errors: List of error messages (empty if valid)
        """
        errors = []

        # Fetch all audit entries from start_audit_no
        entries = (
            self.session.query(AuditLog)
            .filter(AuditLog.audit_no >= start_audit_no)
            .order_by(AuditLog.audit_no.asc())
            .all()
        )

        if not entries:
            return True, []

        # Verify first entry's prev_hash
        first_entry = entries[0]
        if first_entry.prev_hash is not None and start_audit_no == 1:
            # If verifying from the beginning, first entry should have no prev_hash
            errors.append(
                f"First audit entry (audit_no={first_entry.audit_no}) "
                f"should have prev_hash=NULL"
            )

        # Verify each entry's hash
        prev_hash = None
        for i, entry in enumerate(entries):
            # For entries after start_audit_no, use previous entry's hash
            if i > 0:
                prev_hash = entries[i - 1].hash
            elif start_audit_no > 1:
                # For verification starting mid-chain, get the actual prev_hash
                prev_hash = entry.prev_hash

            # Recompute hash
            old_vals = json.loads(entry.old_values) if entry.old_values else None
            new_vals = json.loads(entry.new_values) if entry.new_values else None

            computed_hash = self._compute_hash(
                prev_hash=prev_hash,
                event_type=entry.event_type,
                table_name=entry.table_name,
                record_id=entry.record_id,
                old_values=old_vals,
                new_values=new_vals,
            )

            # Check match
            if computed_hash != entry.hash:
                errors.append(
                    f"Hash mismatch at audit_no={entry.audit_no}: "
                    f"expected {entry.hash}, computed {computed_hash}"
                )

        return len(errors) == 0, errors

    def get_patient_audit_trail(self, patient_id: int) -> list[dict]:
        """
        Get all audit entries for a patient (for review/compliance).

        Args:
            patient_id: Patient ID

        Returns:
            List of audit entries (dicts with audit_no, event_type, etc.)
        """
        entries = (
            self.session.query(AuditLog)
            .filter(AuditLog.patient_id == patient_id)
            .order_by(AuditLog.created_at.asc())
            .all()
        )

        result = []
        for entry in entries:
            result.append({
                "audit_no": entry.audit_no,
                "event_type": entry.event_type,
                "table_name": entry.table_name,
                "record_id": entry.record_id,
                "user_id": entry.user_id,
                "created_at": entry.created_at,
                "old_values": json.loads(entry.old_values)
                if entry.old_values
                else None,
                "new_values": json.loads(entry.new_values)
                if entry.new_values
                else None,
            })
        return result
