# CLAUDE.md — Clinic AI Dashboard

Handoff context for Claude Code. Read this first, then the planning docs in `docs/` (00–06), which are the source of truth. If this file and a doc disagree, the doc wins; flag the conflict.

## What we are building

A single-clinician, offline-first patient records dashboard (general practice, Philippines) with a local LLM that answers questions **about one patient at a time, only from that patient's records, with a citation for every claim**. No patient data ever leaves the machine. Runs on the clinician's 32 GB laptop in v1; later moves to a dedicated clinic machine, then secure remote access (VPN + TLS + MFA) — designed for, not built, in v1.

## The user and how we work

- The user is learning while building. **Every code change comes with four short parts:**
  1. **What** — what the code does (1–2 sentences).
  2. **Why this way** — tied to a requirement in `docs/`.
  3. **Alternatives** — what else we could do and why we didn't.
  4. **Check it** — a command or test that proves it works.
- Work phase by phase (see `docs/06-implementation-plan.md`). Each phase has learning goals and an exit check that must pass before the next starts.
- Small steps; explain before large changes; ask when a decision belongs to the user.
- Update the docs in `docs/` when a decision changes.

## Non-negotiables

- **No real patient data on a dev machine.** Synthetic data only (Synthea). Never commit `*.db`, `keys.json`, `filestore/`, `backups/`, `data/`, or CSVs (see `.gitignore`).
- **Nothing listens beyond 127.0.0.1**; no outbound network calls at runtime; UI loads no external fonts/scripts (strict CSP).
- **Logs never contain patient data** — IDs and event types only.
- AI never diagnoses or recommends treatment; it answers from records, cites `[Sn]`, and says "This isn't in the records" when unsupported. AI text is never auto-saved into a record.
- Health data is sensitive personal information under RA 10173 (Data Privacy Act); design supports the clinician's obligations. Not legal advice.

## Stack (decided)

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0 + Alembic, Pydantic v2 |
| DB | SQLite + SQLCipher (`sqlcipher3`), raw 256-bit key via `PRAGMA key = "x'..'"`, `cipher_compatibility = 4`, FKs ON, WAL |
| Keys | Random data key, wrapped (AES-256-GCM) by Argon2id(passphrase) and by a recovery key; stored in `keys.json` beside the DB |
| Search | SQLite FTS5 + float32 embeddings in a BLOB, brute-force cosine per patient (NumPy) |
| LLM | Ollama on 127.0.0.1; 7–8B instruct model, 4-bit (candidates Llama 3.1 8B, Qwen 2.5 7B; chosen in Phase 5 by eval set); `nomic-embed-text` for embeddings |
| PDF | `pypdf`, `pdfplumber`; OCR (Tesseract) later |
| Frontend | React 18 + TypeScript + Vite, TanStack Query, Tailwind, locally bundled Inter font |
| Tests | pytest, Vitest, Playwright; AI eval set (50 Qs, 15 with absent answers) in `eval/` |
| Lint | ruff (backend, rules E/F/I/B/S), eslint (frontend) |

Schema: 15 tables + FTS index — see `docs/05-backend-schema.md` (users with roles incl. future `secretary`; soft deletes; append-only, hash-chained `audit_log`; `chunks` always carry `patient_id`).

## Repository layout

```text
clinic-dashboard/
  CLAUDE.md            # this file
  backend/
    pyproject.toml     # deps added phase by phase; dev: pytest, ruff
    app/{security,db,api,services,workers}/   # api = HTTP only, services = logic
    tests/test_smoke.py
  frontend/            # Vite app created in Phase 3
  eval/                # AI evaluation set + runner (Phase 5)
  scripts/check_env.py # Phase 0 environment checker
  docs/                # 00-overview … 06-implementation-plan (copy from the claude.ai project)
```

## Commands

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e "backend[dev]"
python scripts/check_env.py          # PASS/WARN/FAIL per tool, exit 1 on any FAIL
cd backend && pytest -q && ruff check . ../scripts && ruff format --check . ../scripts
```

## Status (2026-10-19)

**Phase 1 — Secure Data Core: COMPLETE ✅** | **All 31 tests passing | Linting clean**

### Completed (Step 1–4)

**Step 1: Encrypted Database Engine** ✅
- `backend/app/db/engine.py`: SQLAlchemy + SQLCipher with raw 256-bit key via `PRAGMA key = "x'...'"`
- FK + WAL + cipher_compatibility 4 enabled
- Tests: `test_engine.py` (4 tests)

**Step 2: ORM Models** ✅
- `backend/app/db/models.py`: 15 SQLAlchemy model classes (User, Patient, Encounter, Problem, Medication, Allergy, Chunk, etc.)
- All relationships, constraints, indexes defined
- Soft delete support (deleted_at field)
- AuditLog model (audit_no PK, event_type, table_name, record_id, old/new_values, prev_hash, hash, created_at)
- Tests: `test_models.py` (4 tests)

**Step 3: Alembic Migration** ✅
- `backend/alembic/versions/001_initial_schema.py`: Upgrade/downgrade for all 15 tables
- 9 indexes (PK, FK, soft-delete, time-based)
- FTS5 virtual table (chunks_fts) with sync triggers (INSERT/UPDATE/DELETE)
- Append-only triggers on audit_log (prevents UPDATE/DELETE with "append-only" error)
- Tests: `test_alembic_migrations.py` (8 tests)

**Step 4: Audit Service with Hash Chain** ✅
- `backend/app/services/audit.py`: AuditService class
  - `_compute_hash()`: SHA-256(prev_hash + event_type + table + record_id + old/new values) — deterministic
  - `log_event()`: Creates immutable audit_log entry, returns audit_no for citations [S1], [S2], etc.
  - `verify_hash_chain()`: Recomputes all hashes, detects tampering, supports mid-point validation
  - `get_patient_audit_trail()`: Queries audit entries per patient (chronological, for compliance)
- Tests: `test_audit_service.py` (10 tests)

**Key Achievements:**
- ✅ 31 tests passing (4 engine + 4 models + 8 migration + 10 audit + 3 key_manager + 2 synthea)
- ✅ Linting clean (ruff E/F/I/B/S all pass)
- ✅ No deprecations, no dead code
- ✅ Database schema matches ORM models matches migration
- ✅ Append-only enforcement at DB level (triggers)
- ✅ Hash chain tamper detection verified
- ✅ Patient audit trails queryable

### Next Steps

**Phase 2 — API Layer** (FastAPI):
1. Create `backend/app/api/patients.py`, `encounters.py`, `chunks.py` endpoints
2. Auto-log all changes to audit_log via AuditService
3. Add AI thread API with citation system (pull audit entries by [Sn])
4. User authentication (JWT + roles: clinician, secretary)

**Phase 3 — Frontend** (React + Vite):
1. Patient search + detail view
2. AI chat interface with citations
3. Audit trail viewer for compliance

**Phase 4 — LLM Integration** (Ollama):
1. Pull chat model (Llama 3.1 8B or Qwen 2.5 7B)
2. Embedding model (`nomic-embed-text`)
3. Semantic search (FTS5 + embeddings)
4. Citation retrieval from audit_log

**Phase 5 — Eval & Refinement**:
1. AI eval set (50 Qs, 15 with absent answers)
2. Final tuning of LLM prompts
3. Performance optimization

### Commands (Always Run Before Commit)
```bash
cd backend
pytest -q                    # Run all tests (expect 31 passing)
ruff check . ../scripts      # Linting (expect clean)
ruff format --check . ../scripts
```

### Key Files
- `backend/app/services/audit.py` (280 lines) — Hash chain + tamper detection
- `backend/app/db/models.py` (700 lines) — ORM schema
- `backend/alembic/versions/001_initial_schema.py` (520 lines) — Migrations + triggers
- `backend/app/security/key_manager.py` (150 lines) — Encryption key management
- `backend/app/db/engine.py` (80 lines) — SQLAlchemy + SQLCipher setup

See `STEP4_SUMMARY.md` for detailed audit service documentation.
