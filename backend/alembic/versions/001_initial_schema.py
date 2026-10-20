"""
Initial schema creation from SQLAlchemy models.

This migration creates all 15 tables directly from the ORM definitions in app.db.models.
Because SQLAlchemy can't express some SQL features (FTS5, partial indexes, triggers),
they are added manually in this migration.

Tables:
- users: Clinician and staff accounts
- settings: Global key-value settings
- patients: Patient demographics
- encounters: Clinical visits
- problems: Medical diagnoses and conditions
- medications: Prescriptions and OTC drugs
- allergies: Allergic reactions
- lab_results: Lab test results
- vitals: Vital signs (BP, HR, etc.)
- documents: Uploaded PDFs and images
- chunks: Searchable text pieces from records
- ai_threads: AI conversation sessions
- ai_messages: Individual AI messages (user/assistant)
- ai_citations: Citations for AI message claims
- audit_log: Immutable audit trail (append-only)
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create schema: all 15 tables with constraints, indexes, triggers, FTS."""

    # === USERS ===
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="clinician"),
        sa.Column("license_number", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("role IN ('clinician','secretary')", name="ck_role"),
        sa.CheckConstraint("is_active IN (0,1)", name="ck_is_active"),
    )

    # === SETTINGS ===
    op.create_table(
        "settings",
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # === PATIENTS ===
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_number", sa.String(50), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("middle_name", sa.String(255), nullable=True),
        sa.Column("birth_date", sa.String(10), nullable=False),
        sa.Column("sex", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("emergency_contact", sa.Text(), nullable=True),
        sa.Column("blood_type", sa.String(10), nullable=True),
        sa.Column("allergies_reviewed_at", sa.String(24), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("archived_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_number", name="uq_patient_number"),
        sa.CheckConstraint("sex IN ('female','male','other','unknown')", name="ck_sex"),
    )

    op.create_index("idx_patients_name", "patients", ["last_name", "first_name"])
    op.create_index("idx_patients_birth", "patients", ["birth_date"])
    op.create_index("idx_patient_number", "patients", ["patient_number"])

    # === ENCOUNTERS ===
    op.create_table(
        "encounters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_date", sa.String(10), nullable=False),
        sa.Column("encounter_type", sa.String(50), nullable=False, server_default="consult"),
        sa.Column("chief_complaint", sa.Text(), nullable=True),
        sa.Column("subjective", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("follow_up_date", sa.String(10), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.CheckConstraint(
            "encounter_type IN ('consult','follow_up','procedure','teleconsult','other')",
            name="ck_encounter_type",
        ),
    )

    op.create_index("idx_enc_patient_date", "encounters", ["patient_id", "encounter_date"])
    op.create_index("idx_enc_followup", "encounters", ["follow_up_date"])

    # === PROBLEMS ===
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icd10_code", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("onset_date", sa.String(10), nullable=True),
        sa.Column("resolved_date", sa.String(10), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.CheckConstraint("status IN ('active','resolved','inactive')", name="ck_problem_status"),
    )

    op.create_index("idx_problems_patient", "problems", ["patient_id"])

    # === MEDICATIONS ===
    op.create_table(
        "medications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        sa.Column("drug_name", sa.String(255), nullable=False),
        sa.Column("dose", sa.String(255), nullable=True),
        sa.Column("route", sa.String(50), nullable=True),
        sa.Column("frequency", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("start_date", sa.String(10), nullable=True),
        sa.Column("end_date", sa.String(10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.CheckConstraint(
            "status IN ('active','completed','stopped')", name="ck_medication_status"
        ),
    )

    op.create_index("idx_meds_patient", "medications", ["patient_id", "status"])
    op.create_index("idx_meds_drug", "medications", ["drug_name"])

    # === ALLERGIES ===
    op.create_table(
        "allergies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("substance", sa.String(255), nullable=False),
        sa.Column("reaction", sa.String(255), nullable=True),
        sa.Column("severity", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.CheckConstraint(
            "severity IN ('mild','moderate','severe','unknown')", name="ck_allergy_severity"
        ),
    )

    op.create_index("idx_allergies_patient", "allergies", ["patient_id"])

    # === LAB_RESULTS ===
    op.create_table(
        "lab_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        sa.Column("test_name", sa.String(255), nullable=False),
        sa.Column("result_value", sa.String(255), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("reference_range", sa.String(100), nullable=True),
        sa.Column("collected_date", sa.String(10), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
    )

    op.create_index(
        "idx_labs_patient_test",
        "lab_results",
        ["patient_id", "test_name", "collected_date"],
    )

    # === VITALS ===
    op.create_table(
        "vitals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        sa.Column("vital_name", sa.String(100), nullable=False),
        sa.Column("vital_value", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("measured_at", sa.String(24), nullable=False),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.CheckConstraint(
            "vital_name IN ('BP','HR','RR','Temp','SpO2','Weight','Height')",
            name="ck_vital_name",
        ),
    )

    op.create_index("idx_vitals_patient", "vitals", ["patient_id", "measured_at"])

    # === DOCUMENTS ===
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        sa.Column("lab_result_id", sa.Integer(), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.ForeignKeyConstraint(["lab_result_id"], ["lab_results.id"]),
        sa.UniqueConstraint("file_hash", name="uq_file_hash"),
    )

    op.create_index("idx_documents_patient", "documents", ["patient_id"])

    # === CHUNKS (searchable text) ===
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_table", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("deleted_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
    )

    op.create_index("idx_chunks_patient", "chunks", ["patient_id"])

    # === AI_THREADS ===
    op.create_table(
        "ai_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.String(24), nullable=False),
        sa.Column("archived_at", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_ai_thread_status"),
    )

    op.create_index("idx_ai_threads_patient", "ai_threads", ["patient_id"])

    # === AI_MESSAGES ===
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("feedback", sa.String(50), nullable=True),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"]),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_ai_message_role"),
        sa.CheckConstraint(
            "feedback IN ('helpful','unhelpful','incorrect') OR feedback IS NULL",
            name="ck_ai_message_feedback",
        ),
    )

    op.create_index("idx_ai_messages_thread", "ai_messages", ["thread_id"])

    # === AI_CITATIONS ===
    op.create_table(
        "ai_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("source_table", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["message_id"], ["ai_messages.id"]),
    )

    op.create_index("idx_ai_citations_message", "ai_citations", ["message_id"])

    # === AUDIT_LOG (append-only) ===
    # patient_id has no FK on purpose: entries must survive patient archiving.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.String(24),
            nullable=False,
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))"),
        ),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("hash", name="uq_audit_hash"),
        sa.CheckConstraint(
            "action IN ('unlock','unlock_failed','lock','view','create','update',"
            "'delete','export','ai_query','backup','restore')",
            name="ck_audit_action",
        ),
    )
    op.create_index("idx_audit_time", "audit_log", ["occurred_at"])
    op.create_index("idx_audit_patient", "audit_log", ["patient_id", "occurred_at"])

    # === TRIGGERS FOR AUDIT_LOG (APPEND-ONLY) ===

    op.execute("""
        CREATE TRIGGER audit_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only; cannot update');
        END;
    """)

    op.execute("""
        CREATE TRIGGER audit_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only; cannot delete');
        END;
    """)

    # === CREATE FTS5 VIRTUAL TABLE ===

    op.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            id UNINDEXED,
            patient_id UNINDEXED,
            text
        );
    """)

    # === CREATE TRIGGERS FOR FTS5 SYNC ===

    op.execute("""
        CREATE TRIGGER chunks_ai AFTER INSERT ON chunks
        BEGIN
            INSERT INTO chunks_fts (id, patient_id, text)
            VALUES (new.id, new.patient_id, new.text);
        END;
    """)

    op.execute("""
        CREATE TRIGGER chunks_ad AFTER DELETE ON chunks
        BEGIN
            DELETE FROM chunks_fts WHERE id = old.id;
        END;
    """)

    op.execute("""
        CREATE TRIGGER chunks_au AFTER UPDATE ON chunks
        BEGIN
            UPDATE chunks_fts
            SET text = new.text, patient_id = new.patient_id
            WHERE id = new.id;
        END;
    """)


def downgrade() -> None:
    """Drop schema: triggers, FTS, indexes, tables."""

    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS chunks_au;")
    op.execute("DROP TRIGGER IF EXISTS chunks_ad;")
    op.execute("DROP TRIGGER IF EXISTS chunks_ai;")
    op.execute("DROP TRIGGER IF EXISTS audit_no_delete;")
    op.execute("DROP TRIGGER IF EXISTS audit_no_update;")

    # Drop FTS virtual table
    op.execute("DROP TABLE IF EXISTS chunks_fts;")

    # Drop tables (reverse order of creation to respect FKs)
    op.drop_table("audit_log")
    op.drop_table("ai_citations")
    op.drop_table("ai_messages")
    op.drop_table("ai_threads")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("vitals")
    op.drop_table("lab_results")
    op.drop_table("allergies")
    op.drop_table("medications")
    op.drop_table("problems")
    op.drop_table("encounters")
    op.drop_table("patients")
    op.drop_table("settings")
    op.drop_table("users")
