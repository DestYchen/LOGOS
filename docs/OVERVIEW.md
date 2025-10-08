# SupplyHub Codebase Overview

## 1. High-Level Workflow
1. `POST /batches` (`app/api/routes/batches.py:29`) creates a batch via `app/services/batches.py:19` and prepares filesystem folders under `/srv/supplyhub/batches/{batch_id}`.
2. `POST /batches/{id}/upload` streams uploaded files into `raw/` with unique names (`app/services/batches.py:42`).
3. `POST /batches/{id}/process` enqueues Celery task `supplyhub.process_batch` (`app/services/pipeline.py:203`, `app/workers/tasks.py:17`).
4. `run_batch_pipeline()` (`app/services/pipeline.py:61`) performs OCR, classification, JSON filling, confidence scoring, and persists field versions.
5. Review UI and API (`/batches/{id}/review`, `/web/batches/{id}`) surface low-confidence or missing fields for manual edits (`app/services/review.py:32`).
6. `POST /batches/{id}/review/complete` triggers validation Celery task `supplyhub.validate_batch` (`app/services/pipeline.py:212`).
7. `run_validation_pipeline()` (`app/services/pipeline.py:184`) stores validation messages, generates `report/report.json`, and updates batch status to `DONE`.
8. Monitoring endpoints expose reports and system load (`/batches/{id}/report`, `/archive`, `/system/status`).

## 2. Application Layers
- **API**: FastAPI routers in `app/api/routes` return both JSON and HTML views, using Pydantic schemas from `app/api/schemas.py:11` and dependency-provided sessions (`app/api/dependencies.py:8`).
- **Services**: Business logic in `app/services` handles storage, OCR integration, document classification, LLM communication, validations, reporting, and status snapshots.
- **Core**: Configuration (`app/core/config.py:7`), storage utilities (`app/core/storage.py:22`), database engine/session management (`app/core/database.py:18`), enum definitions (`app/core/enums.py:5`), and document schemas (`app/core/schema.py:21`).
- **Models**: SQLAlchemy ORM models for batches, documents, filled fields, validations, and system snapshots live in `app/models.py:20`.

## 3. Batch Processing Pipeline
- **Text extraction**: `app/services/text_extractor.py:22` determines if OCR is needed; for DOCX/XLSX/TXT it parses text directly.
- **OCR step**: `app/services/ocr.py:17` calls external `dots.ocr` (or stub) and normalizes tokens into `ocr.json`.
- **Classification**: `app/services/classification.py:22` scores document tokens against keyword regexes, defaulting to `UNKNOWN` when no match.
- **JSON filling**: `app/services/json_filler.py:17` posts doc text, file name, and OCR context to the LLM filler (or stub) and stores `filled.json` with flattened fields.
- **Confidence**: `app/services/confidence.py:16` currently supplies placeholder scores to flag items for review.
- **Persistence**: `_store_fields()` in `app/services/pipeline.py:152` version-controls `FilledField` rows, keeping previous entries but marking only the latest as active.

## 4. Data Model & Persistence
- **Batch**: Tracks lifecycle status (`BatchStatus`) and holds many `Document` records (`app/models.py:20`).
- **Document**: Stores filename, MIME, pages, detected type, and file-relative paths to derived JSON (`app/models.py:34`).
- **FilledField**: Versioned key/value pairs with optional bbox/token references, confidence, and provenance (`app/models.py:53`).
- **Validation**: Persisted rule outcomes with references for UI display (`app/models.py:73`).
- **SystemStatusSnapshot**: Time series of queue and worker load (`app/models.py:87`).

## 5. Validation & Reporting
- `app/services/validation.py:60` checks required fields per schema, invoice number consistency, weight variance, currency alignment, and destination coherence.
- `store_validations()` (`app/services/validation.py:171`) replaces prior results each run.
- `app/services/reporting.py:34` compiles `report/report.json` summarizing documents, fields, and validations, and marks batches `DONE` once reporting finishes.
- `app/services/review.py:32` assembles review queues sorted by confidence, supports manual edits via `upsert_field()` (`app/services/review.py:80`), and gates completion through `review_ready()` (`app/services/review.py:126`).

## 6. Workers & Scheduling
- Celery configuration resides in `app/workers/celery_app.py:9`; tasks run inside a dedicated event loop (`app/workers/tasks.py:17`).
- Failures to enqueue remote tasks fall back to local asyncio execution inside `enqueue_batch_processing()` and `enqueue_validation()` (`app/services/pipeline.py:203`).
- Redis acts as both Celery broker and backend, while PostgreSQL stores domain data (see `docker-compose.yml:1`).

## 7. Storage Layout
```
/srv/supplyhub/
  batches/{batch_id}/
    raw/              # original uploads
    derived/{doc_id}/
      ocr.json        # OCR payload
      filled.json     # LLM output with confidence
    preview/{doc_id}/ # image previews (reserved)
    report/report.json
```
Utilities for ensuring folders and generating unique filenames are in `app/core/storage.py:22`.

## 8. Stub & Mock Services
- **OCR Pipeline** (`app/services/ocr.py`, `app/services/dots_ocr_adapter.py`): orchestrates dots.ocr + vLLM in-process (with stub fallback). The legacy `app/mock_services/chatgpt_ocr.py` module remains only for backwards compatibility and is no longer served via uvicorn.
- **ChatGPT JSON Filler Adapter** (`app/mock_services/chatgpt_json_filler.py:57`): uses OpenAI Responses API with templates loaded from `app/mock_services/templates/loader.py:25`; falls back to deterministic stub filling when API keys are missing.
- Templates under `app/mock_services/docs_json` define expected field structures per `DocumentType`.

## 9. Configuration & Deployment Notes
- Environment variables prefixed with `SUPPLYHUB_` map to `Settings` (`app/core/config.py:7`); `SUPPLYHUB_USE_STUB_SERVICES=1` enables internal mocks.
- Async engine/session creation is centralized in `app/core/database.py:18`, and `app/scripts/init_db.py:5` runs migrations-free schema creation.
- `pyproject.toml:8` lists runtime dependencies (FastAPI, SQLAlchemy, Celery, Redis, httpx, PyMuPDF, OpenAI, etc.) plus optional dev extras.
- `docker-compose.yml:1` provisions PostgreSQL, Redis, API, worker, and init containers with shared volume `storage:` for batch artifacts.
