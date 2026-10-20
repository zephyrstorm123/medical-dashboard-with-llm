"""SQLAlchemy ORM models for the clinic dashboard.

All timestamps are ISO-8601 UTC text (sortable as strings).
Clinical dates are YYYY-MM-DD text (no time zone).
Soft deletes use deleted_at; append-only tables (audit_log) use DB-level triggers.
Foreign keys are enforced (PRAGMA foreign_keys = ON).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """Clinician or staff user account.

    v1: one clinician user.
    Future: multiple users with roles (secretary, etc.) managed here.
    Passwords live in keys.json beside the database; deactivating a user
    removes their wrapped key without re-encrypting the database.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    role = Column(
        String(50),
        nullable=False,
        default="clinician",
        server_default="clinician",
    )
    license_number = Column(String(255))
    is_active = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        String(24),
        nullable=False,
        default=lambda: datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("role IN ('clinician','secretary')", name="ck_role"),
        CheckConstraint("is_active IN (0,1)", name="ck_is_active"),
    )

    # Relationships
    audit_log_entries = relationship("AuditLog", back_populates="user")


class Setting(Base):
    """Key-value global settings (e.g., auto_lock_minutes = 5).

    Allows new settings without schema migration.
    """

    __tablename__ = "settings"

    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)


class Patient(Base):
    """A single patient record.

    patient_number: human-facing chart number.
    id: internal row ID, stable across corrections to patient_number.
    archived_at: soft delete; archived patients do not appear in lists.
    allergies_reviewed_at: separates "no allergies" from "never asked".
    Age is computed from birth_date, never stored.
    """

    __tablename__ = "patients"

    id = Column(Integer, primary_key=True)
    patient_number = Column(String(50), unique=True, nullable=False, index=True)
    last_name = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=False)
    middle_name = Column(String(255))
    birth_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    sex = Column(String(20), nullable=False, server_default="unknown")
    phone = Column(String(50))
    address = Column(Text)
    emergency_contact = Column(Text)
    blood_type = Column(String(10))
    allergies_reviewed_at = Column(String(24))
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    updated_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    archived_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint("sex IN ('female','male','other','unknown')", name="ck_sex"),
        Index("idx_patients_name", "last_name", "first_name"),
        Index("idx_patients_birth", "birth_date"),
    )

    # Relationships
    encounters = relationship("Encounter", back_populates="patient")
    problems = relationship("Problem", back_populates="patient")
    medications = relationship("Medication", back_populates="patient")
    allergies = relationship("Allergy", back_populates="patient")
    lab_results = relationship("LabResult", back_populates="patient")
    vitals = relationship("Vital", back_populates="patient")
    documents = relationship("Document", back_populates="patient")
    chunks = relationship("Chunk", back_populates="patient")
    ai_threads = relationship("AIThread", back_populates="patient")


class Encounter(Base):
    """A clinical visit (consult, follow-up, procedure, etc.).

    SOAP format: subjective, objective, assessment, plan.
    Each field can be cited by the AI.
    Composite index on (patient_id, encounter_date DESC) for time-ordered lists.
    Partial index on follow_up_date WHERE deleted_at IS NULL for "due" lists.
    """

    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    encounter_type = Column(
        String(50),
        nullable=False,
        default="consult",
        server_default="consult",
    )
    chief_complaint = Column(Text)
    subjective = Column(Text)
    objective = Column(Text)
    assessment = Column(Text)
    plan = Column(Text)
    follow_up_date = Column(String(10))  # YYYY-MM-DD
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    updated_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "encounter_type IN ('consult','follow_up','procedure','teleconsult','other')",
            name="ck_encounter_type",
        ),
        Index("idx_enc_patient_date", "patient_id", "encounter_date"),
        Index("idx_enc_followup", "follow_up_date"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="encounters")
    problems = relationship("Problem", back_populates="encounter")
    medications = relationship("Medication", back_populates="encounter")
    lab_results = relationship("LabResult", back_populates="encounter")
    vitals = relationship("Vital", back_populates="encounter")
    documents = relationship("Document", back_populates="encounter")


class Problem(Base):
    """An active or resolved medical problem.

    Soft delete with deleted_at.
    encounter_id optional: problem recorded outside a visit.
    """

    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"))
    description = Column(Text, nullable=False)
    icd10_code = Column(String(10))
    status = Column(
        String(50),
        nullable=False,
        default="active",
        server_default="active",
    )
    onset_date = Column(String(10))  # YYYY-MM-DD
    resolved_date = Column(String(10))  # YYYY-MM-DD
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    updated_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint("status IN ('active','resolved','inactive')", name="ck_problem_status"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="problems")
    encounter = relationship("Encounter", back_populates="problems")


class Medication(Base):
    """A prescribed or OTC medication.

    Soft delete. encounter_id optional.
    Dose is text because real doses are "1 tab", "5 mg/kg", etc.
    idx_meds_patient: fast lookup of active meds per patient.
    idx_meds_drug: fast cross-patient lookup (who is on warfarin?).
    """

    __tablename__ = "medications"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"))
    drug_name = Column(String(255), nullable=False)
    dose = Column(String(255))
    route = Column(String(100))
    frequency = Column(String(100))
    indication = Column(Text)
    start_date = Column(String(10))  # YYYY-MM-DD
    end_date = Column(String(10))  # YYYY-MM-DD
    status = Column(
        String(50),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    updated_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint("status IN ('active','stopped','completed')", name="ck_med_status"),
        Index("idx_meds_patient", "patient_id", "status"),
        Index("idx_meds_drug", "drug_name"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="medications")
    encounter = relationship("Encounter", back_populates="medications")


class Allergy(Base):
    """A documented allergy or adverse reaction.

    No encounter_id: allergies are patient state, not visit-specific.
    Soft delete only (no update after deletion).
    """

    __tablename__ = "allergies"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    substance = Column(String(255), nullable=False)
    category = Column(
        String(50),
        nullable=False,
        default="drug",
        server_default="drug",
    )
    reaction = Column(Text)
    severity = Column(
        String(50),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "category IN ('drug','food','environmental','other')",
            name="ck_allergy_category",
        ),
        CheckConstraint(
            "severity IN ('mild','moderate','severe','unknown')",
            name="ck_allergy_severity",
        ),
        Index("idx_allergies_patient", "patient_id"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="allergies")


class LabResult(Base):
    """A lab test result (numeric or text).

    Both value_num and value_text exist; CHECK ensures at least one is set.
    document_id: link back to the PDF this came from (for citations).
    idx_labs_patient_test: fast lookup of one test type over time.
    """

    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"))
    document_id = Column(Integer, ForeignKey("documents.id"))
    test_name = Column(String(255), nullable=False)
    value_num = Column(Float)
    value_text = Column(Text)
    unit = Column(String(100))
    ref_low = Column(Float)
    ref_high = Column(Float)
    flag = Column(String(5))  # N=normal, L=low, H=high, LL=very low, HH=very high
    collected_date = Column(String(24), nullable=False)  # ISO-8601
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "value_num IS NOT NULL OR value_text IS NOT NULL",
            name="ck_lab_has_value",
        ),
        CheckConstraint("flag IN ('N','L','H','LL','HH') OR flag IS NULL", name="ck_lab_flag"),
        Index("idx_labs_patient_test", "patient_id", "test_name", "collected_date"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="lab_results")
    encounter = relationship("Encounter", back_populates="lab_results")
    document = relationship("Document", back_populates="lab_results")


class Vital(Base):
    """Vital signs recorded at a point in time.

    All fields optional (not all vitals taken at every visit).
    idx_vitals_patient: fetch most recent vitals, newest first.
    """

    __tablename__ = "vitals"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"))
    measured_at = Column(String(24), nullable=False)  # ISO-8601
    systolic = Column(Integer)
    diastolic = Column(Integer)
    heart_rate = Column(Integer)
    resp_rate = Column(Integer)
    temp_c = Column(Float)
    spo2 = Column(Integer)
    weight_kg = Column(Float)
    height_cm = Column(Float)
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (Index("idx_vitals_patient", "patient_id", "measured_at"),)

    # Relationships
    patient = relationship("Patient", back_populates="vitals")
    encounter = relationship("Encounter", back_populates="vitals")


class Document(Base):
    """An uploaded file (lab result PDF, referral letter, imaging report, etc.).

    File stored encrypted on disk under random stored_name.
    sha256: detect duplicates and tampering.
    extracted_text: full-text search without decrypting files.
    index_status: tracks whether text extraction succeeded.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"))
    doc_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    doc_date = Column(String(10))  # YYYY-MM-DD
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    stored_name = Column(String(255), unique=True, nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    extracted_text = Column(Text)
    index_status = Column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    index_error = Column(Text)
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    deleted_at = Column(String(24))

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ("
            "'lab_result','referral','imaging_report','prescription',"
            "'certificate','other')",
            name="ck_doc_type",
        ),
        CheckConstraint(
            "index_status IN ('pending','indexed','no_text','failed')",
            name="ck_index_status",
        ),
        Index("idx_docs_patient", "patient_id", "doc_date"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="documents")
    encounter = relationship("Encounter", back_populates="documents")
    lab_results = relationship("LabResult", back_populates="document")


class Chunk(Base):
    """A searchable text piece extracted from a clinical record.

    Always tagged with patient_id for privacy (filter before similarity search).
    source_table + source_id: points back to the original record.
    No FK constraint intentionally (points at 7 different tables).
    Service layer deletes chunks when a record is deleted or edited.
    embedding: raw float32 bytes (768 dims × 4 = 3 KB per chunk).
    embedding_model: allows re-embedding if model changes.
    """

    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    source_table = Column(String(50), nullable=False)
    source_id = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0, server_default="0")
    record_date = Column(String(10))  # YYYY-MM-DD
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    embedding = Column(LargeBinary)  # Float32 vector as raw bytes
    embedding_model = Column(String(100))
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "source_table IN ("
            "'encounters','problems','medications','allergies',"
            "'lab_results','vitals','documents')",
            name="ck_source_table",
        ),
        UniqueConstraint("source_table", "source_id", "chunk_index", name="uq_chunk_source"),
        Index("idx_chunks_patient", "patient_id"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="chunks")


class AIThread(Base):
    """A conversation thread (one patient, multiple Q&A pairs)."""

    __tablename__ = "ai_threads"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    title = Column(String(255))
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )

    # Relationships
    patient = relationship("Patient", back_populates="ai_threads")
    messages = relationship("AIMessage", back_populates="thread")


class AIMessage(Base):
    """A single message in an AI thread.

    role: 'user' (clinician asks) or 'assistant' (AI answers).
    model_name, prompt_version: explains *why* the answer looked this way.
    latency_ms: performance tracking.
    feedback: "wrong" marks answers for the evaluation set.
    """

    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True)
    thread_id = Column(Integer, ForeignKey("ai_threads.id"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    model_name = Column(String(100))
    prompt_version = Column(String(50))
    latency_ms = Column(Integer)
    feedback = Column(String(50))
    created_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_ai_role"),
        CheckConstraint(
            "feedback IN ('helpful','wrong') OR feedback IS NULL",
            name="ck_feedback",
        ),
        Index("idx_ai_msg_thread", "thread_id", "id"),
    )

    # Relationships
    thread = relationship("AIThread", back_populates="messages")
    citations = relationship("AICitation", back_populates="message")


class AICitation(Base):
    """A source citation in an AI answer.

    snippet: the exact text the AI saw (copied, not linked, so it survives
             if the original chunk is edited or deleted).
    chunk_id: optional link back to the chunk (for exploring the context).
    source_table + source_id: always present, no FK (points at 7 tables).
    is_valid: marks citations the clinician marks as incorrect.
    """

    __tablename__ = "ai_citations"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("ai_messages.id"), nullable=False)
    label = Column(String(50), nullable=False)  # [S1], [S2], etc.
    chunk_id = Column(Integer)  # FK intentionally omitted (chunks may be deleted)
    source_table = Column(String(50), nullable=False)
    source_id = Column(Integer, nullable=False)
    snippet = Column(Text, nullable=False)
    is_valid = Column(Integer, nullable=False, default=1, server_default="1")

    # Constraints
    __table_args__ = (CheckConstraint("is_valid IN (0,1)", name="ck_citation_valid"),)

    # Relationships
    message = relationship("AIMessage", back_populates="citations")


class AuditLog(Base):
    """Append-only event log (cannot be updated or deleted).

    DB-level triggers enforce immutability.
    Hash chain: hash = SHA-256(prev_hash + occurred_at + user_id + action +
    entity_type + entity_id + patient_id + detail); see app/services/audit.py.
    patient_id: no FK (entries must survive if patient is archived).
    detail: JSON with IDs and field names only, never clinical text.
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    occurred_at = Column(
        String(24),
        nullable=False,
        server_default=func.strftime("%Y-%m-%dT%H:%M:%fZ", "now"),
    )
    action = Column(String(20), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    patient_id = Column(Integer, nullable=True)  # No FK (survives if patient archived)
    detail = Column(Text, nullable=True)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "action IN ('unlock','unlock_failed','lock','view','create','update',"
            "'delete','export','ai_query','backup','restore')",
            name="ck_audit_action",
        ),
        UniqueConstraint("hash", name="uq_audit_hash"),
        Index("idx_audit_time", "occurred_at"),
        Index("idx_audit_patient", "patient_id", "occurred_at"),
    )

    # Relationships
    user = relationship("User", back_populates="audit_log_entries")
