# SupplyHub Backend - Current State

Document reconciliation service for foreign-trade paperwork. FastAPI delivers both JSON APIs and a minimal Jinja web UI, with Celery workers orchestrating OCR, LLM-based field extraction, review, and validation workflows.

## Status Snapshot
- **Working:** batch CRUD plus upload (app/api/routes/batches.py:28), background pipeline fallback when Celery unavailable (app/services/pipeline.py:281), report generation (app/services/reporting.py:34), validation rules persisted to DB (app/services/validation.py:940), HTML review UI (app/api/routes/web.py:31).
- **Partially implemented:** OCR and LLM adapters present but need real API keys; they default to deterministic stubs (app/services/ocr.py:17, app/services/json_filler.py:17). Confidence scoring is random and unsuitable for production (app/services/confidence.py:9). Document classification only covers a subset of DocumentType values (app/services/classification.py:9).
- **Missing:** Production-ready frontend, authentication and authorization, migrations, automated tests, monitoring dashboards, hardened AI integrations.

## Architecture Overview
- **API entrypoint** mounts batch storage and routers (app/main.py:13); /ping provides basic health (app/main.py:22).
- **Config and infrastructure** sourced from Settings (app/core/config.py:7); storage helpers create /srv/supplyhub/batches/{id} tree for raw, derived, and report assets (app/core/storage.py:22).
- **Data model** (Batch, Document, FilledField, Validation, SystemStatusSnapshot) defined with SQLAlchemy (app/models.py:20).
- **Schemas and validation baseline** enumerate expected fields per document type (app/core/schema.py:9) and feed the rule engine (app/services/validation.py:60).
- **Services layer**
  - Batch lifecycle utilities with PDF splitter (app/services/batches.py:59).
  - Pipeline orchestrating OCR -> classification -> JSON fill -> scoring -> persistence (app/services/pipeline.py:78) and validation/reporting loop (app/services/pipeline.py:262).
  - Manual review helpers (app/services/review.py:32) and system metrics snapshotting (app/services/status.py:12, app/services/status.py:50).
  - Stubbed confidence scoring (app/services/confidence.py:9) and regex-based classification (app/services/classification.py:9).
- **Workers** boot Celery with Redis broker and backend (app/workers/celery_app.py:9, app/workers/tasks.py:17). Failover runs tasks inline via asyncio if Celery dispatch fails (app/services/pipeline.py:281).
- **Frontend surface** served via FastAPI templating (app/api/routes/web.py:31, app/templates/batch.html) for upload, batch view, and manual field confirmation; text is currently Russian and styling minimal.
- **Documentation assets:** high-level overview (docs/OVERVIEW.md), detailed Russian-language spec (SPEC.md). Integration scripts for OCR and LLM testing live under 	est_ocr/.

## Data Flow
1. Create batch -> batches.create_batch() (app/api/routes/batches.py:28) persists a row and storage folders (app/services/batches.py:59).
2. Upload files -> sanitized, optionally split per PDF page, stored under 
aw/ (app/services/batches.py:81).
3. Process request enqueues Celery; fallback runs local pipeline (app/services/pipeline.py:281). The pipeline writes OCR payloads, flattened filled fields, and updates document status (app/services/pipeline.py:118, app/services/pipeline.py:230).
4. Review endpoints surface low-confidence and missing fields (app/api/routes/batches.py:64, app/services/review.py:32) sorted by confidence.
5. Manual edits create new FilledField versions (app/services/review.py:80). Completion triggers validation (app/services/pipeline.py:262) and report generation with warnings merged into validations (app/services/reporting.py:34).
6. Reports and archive retrieval read from the filesystem (app/services/reports.py:9, app/api/routes/archive.py:17). /system/status returns DB stats plus the latest snapshot (app/api/routes/system.py:14).

## Directory Layout
`
app/
  api/             # FastAPI routers and schemas
  core/            # config, storage, enums, document schema
  mock_services/   # ChatGPT OCR and JSON filler adapters plus templates
  scripts/         # init_db helper
  services/        # business logic (pipeline, validation, review, etc.)
  templates/       # HTML views for manual review
  workers/         # Celery wiring
docs/              # human-facing docs
test_ocr/          # local adapters smoke tests plus sample assets
Dockerfile, docker-compose.yml, SPEC.md, pyproject.toml
`

## Configuration and Deployment
- Runtime dependencies declared in pyproject.toml; Docker image installs in editable mode for live reload.
- docker-compose.yml provisions Postgres, Redis, API, worker, init-db, and shared storage volume; worker expects OCR and JSON services on host ports 9001 and 9002.
- Environment variables prefixed SUPPLYHUB_ configure DB, Redis, Celery, paths, and stub toggles (app/core/config.py:7). SUPPLYHUB_USE_STUB_SERVICES=1 forces internal mocks.

## External and Mock Services
- ChatGPT-based OCR adapter (app/mock_services/chatgpt_ocr.py:79) and JSON filler adapter (app/mock_services/chatgpt_json_filler.py:57) require OpenRouter or OpenAI keys; both gracefully fall back to deterministic stubs and load JSON templates from app/mock_services/docs_json/.
- CLI smoke tests (	est_ocr/testim.py, 	est_ocr/test_json_filler.py) can hit adapters or external endpoints directly.

## Current Gaps and Risks
- **AI quality:** classification misses PROFORMA and SPECIFICATION types, confidence is random, OCR and LLM prompts not tuned, no grounding in document schema beyond template merge.
- **Frontend UX:** Jinja pages lack pagination, diffing, previews, keyboard shortcuts, or upload progress; no localization toggle or auth.
- **Ops:** no Alembic migrations, tests, tracing, or rate limiting; error messages partly in Russian, inconsistent logging; warnings stored in batch meta but not surfaced elsewhere.
- **Security and compliance:** unauthenticated endpoints, no audit logging, static file serving exposes the entire storage root.

## Backlog and Next Steps
### Frontend
1. Replace Jinja views with a modern SPA (or richer server-rendered UI) supporting live status, previews, validation drilldown, and multi-user review.
2. Implement authentication, session management, and role-based access.
3. Improve localization (RU and EN), accessibility, and error messaging consistency.

### AI and Document Processing
1. Build a deterministic confidence model (for example leverage OCR confidence and schema heuristics) to replace random scoring (app/services/confidence.py:9).
2. Extend classification beyond regex keywords (app/services/classification.py:9) using ML or template matching; cover all DocumentType values.
3. Integrate production OCR and LLM endpoints with retry, backoff, payload chunking, token budgets, and observability.
4. Enhance schema handling for nested product tables and support multi-page or multi-product outputs; add a normalization layer before validation.
5. Capture provenance metadata (model version, prompt ID) alongside FilledField records.

### Platform and Quality
1. Introduce migrations (Alembic) and seed scripts; add unit and integration tests (pytest plus httpx) and CI.
2. Harden storage (per-tenant directories, antivirus, cleanup of derived artifacts).
3. Add structured logging, metrics, and alerting around Celery queues and pipeline failures.
4. Implement concurrency safeguards (idempotent processing, deduplication) and batch cancellation flows.
5. Document API schema via OpenAPI tags and provide a Postman or Insomnia collection.

Artifacts referenced above:
- app/main.py:13
- app/core/config.py:7
- app/core/storage.py:22
- app/models.py:20
- app/core/schema.py:9
- app/api/routes/batches.py:28
- app/api/routes/web.py:31
- app/services/batches.py:59
- app/services/pipeline.py:78
- app/services/pipeline.py:118
- app/services/pipeline.py:230
- app/services/pipeline.py:262
- app/services/pipeline.py:281
- app/services/classification.py:9
- app/services/confidence.py:9
- app/services/json_filler.py:17
- app/services/ocr.py:17
- app/services/review.py:32
- app/services/review.py:80
- app/services/validation.py:940
- app/services/reporting.py:34
- app/services/status.py:12
- app/api/routes/archive.py:17
- app/api/routes/system.py:14
- app/services/reports.py:9
- docs/OVERVIEW.md
- SPEC.md
