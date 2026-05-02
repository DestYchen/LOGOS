# LOGOS / SupplyHub Specification

This file describes the project as it exists in the repository today. It is an
implementation spec, not an aspirational product brief. When there is a
disagreement, the current source code under `app/`, `tests/`, and
`test frontend/` is the source of truth.

The codebase uses both names:

- `SupplyHub` is the backend package and default FastAPI app name.
- `LOGOS` is the user-facing product name in the current frontend copy.

## 1. Product Purpose

LOGOS is an internal document-processing tool for logistics and foreign-trade
document packages. A user uploads the files for one shipment/package, the system
extracts text, classifies each document, fills normalized JSON fields, compares
those fields across documents, and produces a reviewable report.

The core business goal is to replace manual cross-checking of shipment document
sets with a repeatable workflow:

1. Create a packet/batch.
2. Upload documents.
3. Preview, rotate, delete, and confirm the upload set.
4. Run OCR/text extraction, classification, JSON filling, confidence scoring,
   validation, and report generation.
5. Review low-confidence or missing values with document previews.
6. Re-run validation/reporting after corrections.
7. Export the final matrix/report as JSON or XLSX.

The service is intended for an internal office network. It currently has no
authentication or role model.

## 2. Current Status

Implemented and active:

- Batch creation, upload, listing, deletion, and history.
- Upload preprocessing for PDF, image, DOCX, XLSX/XLSM, and text-like files.
- PDF/image preview generation and PDF page rotation before processing.
- Multi-page PDF splitting into one `Document` row per page.
- Celery workers with local async fallback when Celery dispatch fails.
- In-process `dots.ocr` adapter that talks to a vLLM/OpenAI-compatible endpoint.
- Optional HTTP OCR endpoint override.
- Regex and optional LLM document classification.
- Local JSON filler HTTP adapter plus remote filler router.
- Optional OpenRouter-backed remote JSON filler with JSON repair/retry logic.
- Field versioning for automated and manual values.
- Review screens for missing/low-confidence fields and manual corrections.
- Cross-document validation, document matrix, product matrix, JSON report, and
  XLSX export.
- React/Vite frontend served from FastAPI when built.
- Local archive mode for raw uploads and filler request/response logging.
- Feedback form with local ticket storage and Telegram forwarding.
- Daily Telegram summary task scheduled by Celery beat.

Known gaps and risks:

- No authentication, authorization, audit trail, tenant isolation, or rate
  limiting.
- No Alembic migration workflow in use; `app.scripts.init_db` creates tables
  directly.
- `/files` serves the configured storage root through `StaticFiles`.
- OCR and filler quality depend on external/local model runtime configuration.
- Automated tests currently cover only selected document profile, validation
  profile, and product matrix behavior.
- Some documentation and source comments are stale compared with the current
  implementation.
- Several user-facing strings are Russian, while the project documentation is
  mixed English/Russian.
- Feedback Telegram credentials must be kept out of source code before any
  production deployment.

## 3. Technology Stack

Backend:

- Python 3.11+
- FastAPI
- SQLAlchemy async ORM
- PostgreSQL 15+
- Redis
- Celery and Celery beat
- Pydantic v2 / pydantic-settings
- httpx and requests
- PyMuPDF (`fitz`) for PDF handling and previews
- LibreOffice (`soffice`) for DOCX/XLSX to PDF conversion
- python-docx and openpyxl for direct text extraction
- Pillow and numpy/scikit-learn for OCR adapter support
- OpenAI SDK for vLLM/OpenRouter-compatible APIs

Frontend:

- React 18
- Vite
- TypeScript
- React Router
- Tailwind CSS
- Radix UI primitives
- lucide-react icons

Deployment:

- Dockerfile installs the editable Python package.
- `docker-compose.yml` provisions Postgres, Redis, API, worker, beat, init-db,
  doc-classifier, and remote-json-filler services.
- Shared storage is mounted at `SUPPLYHUB_BASE_DIR`, `/data/storage` in compose.

## 4. Repository Layout

```text
app/
  api/                  FastAPI route modules and Pydantic schemas
  core/                 config, storage helpers, enums, schemas, DB wiring
  mock_services/        classifier/filler adapters, hints, templates, samples
  services/             pipeline, OCR, filler, review, validation, reporting
  templates/            legacy/minimal Jinja pages
  workers/              Celery app and task definitions
docs/                   short architecture overview
tests/                  focused pytest coverage
test frontend/          React frontend source and build config
test_ocr/               OCR/filler smoke test assets
local_archive/          optional local request/response archive
SPEC.md                 this file
README.md               current-state backend overview
```

## 5. Runtime Configuration

Settings live in `app/core/config.py` and use the `SUPPLYHUB_` environment
prefix.

Important settings:

- `SUPPLYHUB_DATABASE_URL`
- `SUPPLYHUB_REDIS_URL`
- `SUPPLYHUB_CELERY_BROKER_URL`
- `SUPPLYHUB_CELERY_RESULT_BACKEND`
- `SUPPLYHUB_BASE_DIR`
- `SUPPLYHUB_BLOCKED_DOC_PATTERNS_PATH`
- `SUPPLYHUB_OCR_ENDPOINT`
- `SUPPLYHUB_JSON_FILLER_ENDPOINT`
- `SUPPLYHUB_REMOTE_JSON_FILLER_ENDPOINT`
- `SUPPLYHUB_REMOTE_JSON_FILLER_PROVIDER`
- `SUPPLYHUB_REMOTE_JSON_FILLER_TYPES_PATH`
- `SUPPLYHUB_DOC_CLASSIFIER_ENDPOINT`
- `SUPPLYHUB_LOW_CONF_THRESHOLD`
- `SUPPLYHUB_LOCAL_ARCHIVE_MODE`
- `SUPPLYHUB_LOCAL_ARCHIVE_DIR`
- `SUPPLYHUB_USE_STUB_SERVICES`
- `SUPPLYHUB_TELEGRAM_BOT_TOKEN`
- `SUPPLYHUB_TELEGRAM_CHAT_ID`

OCR adapter settings are read directly from `DOTS_OCR_*` environment variables,
including `DOTS_OCR_REPO`, `DOTS_OCR_VLLM_BASE`, `DOTS_OCR_VLLM_HOST`,
`DOTS_OCR_VLLM_PORT`, model names, token budgets, preprocessing options, and
debug controls.

OpenRouter/remote filler settings are read from `OPENROUTER_*`,
`SUPPLYHUB_OPENROUTER_API_KEY`, and
`SUPPLYHUB_REMOTE_JSON_FILLER_API_KEY*`.

## 6. Domain Model

ORM models are in `app/models.py`.

### Batch

Represents one uploaded document packet.

Fields:

- `id`
- `created_at`
- `updated_at`
- `created_by`
- `status`
- `meta`
- `documents`
- `validations`

Important `meta` keys currently used:

- `title`
- `prep_complete`
- `document_profile`
- `processing_run`
- `processing_warnings`
- `active_tasks`
- `cancel_info`

### Document

Represents one stored file inside a batch. A multi-page PDF is split into
separate documents during upload.

Fields:

- `id`
- `batch_id`
- `filename`
- `mime`
- `pages`
- `doc_type`
- `status`
- `ocr_path`
- `filled_path`
- timestamps
- `fields`

### FilledField

Represents one extracted or manually edited field value. Fields are versioned:
old values are retained and only one row per `doc_id + field_key` is marked
`latest=True`.

Fields:

- `field_key`
- `value`
- `page`
- `bbox`
- `token_refs`
- `confidence`
- `source`
- `version`
- `latest`
- `edited_by`
- `edited_at`

### Validation

Represents one validation result for a batch.

Fields:

- `rule_id`
- `severity`: `ok`, `warn`, or `error`
- `message`
- `refs`

### SystemStatusSnapshot

Stores cached worker/queue/load values used by `/system/status`.

## 7. Status Model

Batch statuses:

```text
NEW
PREPARED
TEXT_READY
CLASSIFIED
FILLED_AUTO
FILLED_REVIEWED
VALIDATED
DONE
FAILED
CANCEL_REQUESTED
CANCELLED
```

Document statuses:

```text
NEW
TEXT_READY
CLASSIFIED
FILLED_AUTO
FILLED_REVIEWED
FAILED
```

Current lifecycle:

1. `POST /batches` or `/web/upload` creates `NEW` batch with
   `prep_complete=false`.
2. Uploading files stores document rows and normally sets batch `PREPARED`.
3. Confirming preparation sets `prep_complete=true`, stores the selected
   document profile, creates `processing_run` metadata, and enqueues processing.
4. Processing performs OCR/text extraction, classification, optional document
   merging, JSON filling, confidence scoring, and field persistence.
5. If all documents fail, batch becomes `FAILED`; otherwise it becomes
   `FILLED_AUTO`.
6. The pipeline currently auto-runs validation/reporting after successful
   processing, so a batch can move to `VALIDATED` and then `DONE` without an
   explicit review-complete action.
7. Manual field edits, type changes, and refills run validation/reporting again.
8. Completing review marks documents and batch `FILLED_REVIEWED`, then enqueues
   validation/reporting.
9. Deletion marks `CANCEL_REQUESTED`, cancels local/Celery tasks when possible,
   removes DB rows, removes batch files, and leaves the operation as deleted.

## 8. Storage Layout

Storage is rooted at `settings.base_dir`, default `/srv/supplyhub`.

```text
{base_dir}/
  batches/{batch_id}/
    raw/
      uploaded and generated source files
    derived/{doc_id}/
      ocr.json
      filled.json
    preview/{doc_id}/
      page_1.png
      page_2.png
      ...
    report/
      report.json
  feedback/
    pending/{ticket_id}/
      payload.json
      files/
    sent/
```

FastAPI mounts the entire base directory as `/files`.

When `SUPPLYHUB_LOCAL_ARCHIVE_MODE=1`, additional copies of raw files and filler
request/response payloads are written under `SUPPLYHUB_LOCAL_ARCHIVE_DIR`.

## 9. Upload and Preparation

Upload handling lives primarily in `app/services/batches.py`.

Accepted inputs by current implementation:

- PDF
- PNG/JPG/JPEG
- DOCX
- XLSX/XLSM
- plain text-like files handled by the parser path, including TXT, CSV, TSV,
  JSON, and Markdown

Upload behavior:

- Filenames are normalized to a filesystem-safe basename.
- Name collisions are resolved with numeric suffixes.
- Images are converted to PDF using PyMuPDF.
- DOCX/XLSX/XLSM files are converted to PDF with LibreOffice when possible.
- Multi-page PDFs are split into one-page PDF files, each represented as a
  separate `Document`.
- Single-page PDFs get a preview PNG.
- Uploads can be added to an existing batch unless the batch is cancelled.
- Adding files to a processed batch resets `prep_complete=false`; confirming
  again runs the delta pipeline for newly added documents.
- Before prep confirmation, PDFs can be rotated and documents can be deleted.

## 10. Document Profiles

Profiles live in `app/core/document_profiles.py`.

Current profiles:

- `standard`
- `china_sea`

`standard` expected document display order:

```text
CONTRACT
ADDENDUM
PROFORMA
INVOICE
BILL_OF_LADING
CMR
PACKING_LIST
PRICE_LIST_1
PRICE_LIST_2
QUALITY_CERTIFICATE
VETERINARY_CERTIFICATE
EXPORT_DECLARATION
SPECIFICATION
CERTIFICATE_OF_ORIGIN
FORM_A
EAV
CT-3
T1
```

`china_sea` expected document display order:

```text
CONTRACT
ADDENDUM
PROFORMA
BILL_OF_LADING
PACKING_LIST
INVOICE
PRICE_LIST_1
PRICE_LIST_2
VETERINARY_CERTIFICATE
QUALITY_CERTIFICATE
CERTIFICATE_OF_ORIGIN
EXPORT_DECLARATION
SPECIFICATION
```

`ADDENDUM` is a display placeholder and currently has no real `DocumentType`.
Profile selection affects the expected-document UI, field matrix order, and
which validation rules are active.

## 11. Document Types

Current `DocumentType` values:

```text
UNKNOWN
EXPORT_DECLARATION
INVOICE
PACKING_LIST
BILL_OF_LANDING
PROFORMA
SPECIFICATION
PRICE_LIST_1
PRICE_LIST_2
QUALITY_CERTIFICATE
CERTIFICATE_OF_ORIGIN
VETERINARY_CERTIFICATE
CMR
CONTRACT
CONTRACT_1
CONTRACT_2
CONTRACT_3
FORM_A
EAV
CT-3
T1
```

`CONTRACT_1`, `CONTRACT_2`, and `CONTRACT_3` are internal intermediate types.
When all three are present and OCR is complete, the pipeline merges them into
one public `CONTRACT` document and removes the intermediate rows/files.

Multiple `VETERINARY_CERTIFICATE` parts are similarly merged into one
`VETERINARY_CERTIFICATE` document before filling.

## 12. Schema and Fields

Schemas live in `app/core/schema.py` and are the source of truth for expected
fields. A schema is a `DocumentSchema` containing `FieldSchema` entries:

- `key`
- `required`
- `label`
- `dtype`
- `fmt`
- `anchors`
- optional nested `children`

Many document types contain a nested `products` field. During persistence,
nested product fields are flattened:

```text
products.product_1.name_product
products.product_1.latin_name
products.product_1.size_product
products.product_1.packages
...
```

Common product fields include:

- `name_product`
- `latin_name`
- `size_product`
- `unit_box`
- `packages`
- `net_weight`
- `net_weight_with_glaze`
- `net_weight_with_ice`
- `net_weight_with_glaze_and_pack`
- `gross_weight`
- `price_per_unit`
- `price_per_KG`
- `total_price`
- `factory_number`
- `date_of_production`
- `seal_number`

The report field matrix currently compares these top-level aliases:

```text
proforma_date
proforma_no
invoice_date
invoice_no
country_of_origin
producer
buyer
seller
exporter
importer
incoterms
terms_of_payment
bank_details
total_price
destination
vessel
container_no
veterinary_seal
linear_seal
veterinary_certificate_no
veterinary_certificate_date
HS_code / commodity_code
```

## 13. OCR and Text Extraction

Text extraction is split between parser extraction and OCR.

Parser path:

- Non-image documents are parsed with `python-docx`, `openpyxl`, or direct text
  reading.
- Parser text is converted into a synthetic token with confidence `1.0` when no
  OCR tokens exist.

OCR path:

- PDF, PNG, JPG, and JPEG require OCR.
- `app/services/ocr.py` calls either:
  - an optional HTTP OCR endpoint from `SUPPLYHUB_OCR_ENDPOINT`, or
  - the in-process `DotsOCRAdapter` from `app/services/dots_ocr_adapter.py`.
- The in-process adapter expects a local `dots.ocr` repo and a vLLM-compatible
  endpoint.
- It renders PDF pages/images, calls vLLM, parses layout JSON, refines empty
  text regions when configured, saves preview images, and emits flat tokens.

Normalized OCR token shape:

```json
{
  "id": "p0_t12",
  "text": "INVOICE",
  "conf": 0.94,
  "bbox": [10, 20, 110, 42],
  "page": 1,
  "category": "Text"
}
```

`ocr.json` shape:

```json
{
  "doc_id": "uuid",
  "tokens": []
}
```

## 14. Classification

Classification lives in `app/services/classification.py`.

Current logic:

- Priority regexes handle strong signals such as proforma invoice, commercial
  invoice headers, packing list, specification, price list type, CMR, export
  declaration, T1, veterinary certificate, and contract parts.
- Price list documents are split into `PRICE_LIST_1` and `PRICE_LIST_2` based
  on per-kg vs per-pack price signals.
- Contract part classification detects `CONTRACT_1`, `CONTRACT_2`, and
  `CONTRACT_3`.
- If `SUPPLYHUB_DOC_CLASSIFIER_ENDPOINT` is configured, an external classifier
  can be called after the priority checks.
- Remaining classification falls back to keyword scoring over OCR tokens and
  full document text.
- `UNKNOWN` documents are marked failed by the processing pipeline.

## 15. JSON Filling

The pipeline sends document text and OCR tokens to a JSON filler and expects a
JSON object with fields.

Local filler:

- Implemented in `app/services/json_filler.py`.
- Sends HTTP requests to `SUPPLYHUB_JSON_FILLER_ENDPOINT`.
- Includes `doc_id`, `doc_type`, `doc_text`, optional `file_name`, and optional
  `tokens`.
- Filters Cyrillic-heavy tokens for `SPECIFICATION`.
- Has a stub mode when `SUPPLYHUB_USE_STUB_SERVICES=1`.

Remote filler routing:

- Implemented in `app/services/json_filler_router.py`.
- `app/remote_filler_types.txt` lists document types routed to remote filler.
- Current remote types in the file are:

```text
EXPORT_DECLARATION
CONTRACT
VETERINARY_CERTIFICATE
```

- Remote calls fall back to local filler on timeout, remote error, or remote
  stub response.

Remote filler providers:

- `http`: call `SUPPLYHUB_REMOTE_JSON_FILLER_ENDPOINT`.
- `openrouter`: build prompts from schema templates and hints, call OpenRouter
  or compatible API, repair/extract JSON, and merge main/product outputs.

The filler is not trusted for confidence. The pipeline computes confidence
after filling.

## 16. Confidence Scoring

Confidence scoring lives in `app/services/confidence.py`.

Current behavior:

- If a filled field has `token_refs` and OCR tokens have matching IDs, confidence
  is the average of referenced token `conf` values.
- Numeric token-ref fallbacks are supported best effort.
- If no usable refs or token confidences are available, confidence falls back to
  `1.0`.
- Scores are clamped to `[0.0, 1.0]`.
- Manual user edits are stored with confidence `1.0` and source `user`.

This is simpler than the older formula described in previous specs. It does not
yet apply anchor, format, or table bonuses.

## 17. Field Normalization and Persistence

Pipeline filling logic:

1. Load OCR tokens from `ocr.json` or parser text.
2. Build `doc_text` from token text plus parser text.
3. Send text/tokens to the selected JSON filler.
4. Flatten nested field structures into dot-separated keys.
5. Add default `bbox`, `token_refs`, and `source` where absent.
6. Compute confidence.
7. Derive missing `page` from token refs where possible.
8. Derive missing `bbox` from referenced token boxes where possible.
9. Write `derived/{doc_id}/filled.json`.
10. Insert new `FilledField` versions and mark previous latest rows false.

## 18. Review and Correction

Review data is built from latest fields and document schema.

Field states include:

- `missing`
- `low_confidence`
- `ok`
- `extra`
- `product`
- `unknown_type`

Current threshold is `SUPPLYHUB_LOW_CONF_THRESHOLD`, default `0.75`.

User actions:

- Update a field value.
- Confirm an existing field value.
- Mark a field missing by saving an empty/null value.
- Change document type and refill from existing OCR.
- Refill a document using its current type.
- Complete review when no pending fields remain.

Manual updates and refills trigger validation/reporting again.

## 19. Validation

Validation lives in `app/services/validation.py`.

Rule families:

- Required field checks from `app/core/schema.py`.
- Date ordering rules such as proforma before invoice, bill of landing after
  sources, veterinary certificate before bill of landing, export declaration
  after bill of landing, and profile-filtered transport rules.
- Anchored equality rules for contract number, additional agreements, country
  of origin, total price, producer, incoterms, payment terms, bank details,
  exporter, recipient/buyer alignment, proforma number, invoice number,
  veterinary seal, and linear seal.
- Group equality rules for buyer, seller, container number, vessel, and
  importer.
- Invoice number alignment, currency consistency, and destination alignment.
- Product row comparisons by product identity (`name_product`, `latin_name`,
  `size_product`), missing/extra product rows, count mismatches, and selected
  product field mismatches.
- Field matrix and field matrix diff snapshots.

Validation output is stored in the `validations` table, replacing previous
results for the batch each run.

## 20. Reporting

Reporting lives in `app/services/reporting.py` and `app/services/reports.py`.

`report/report.json` contains:

- `batch_id`
- `status`
- `generated_at`
- `documents`
- latest field values with confidence, source, page, and bbox
- `validations`
- batch `meta`
- `product_comparisons`
- `product_matrix_columns`
- `product_matrix`

The frontend derives additional views:

- field matrix
- field matrix diff
- validation matrix
- product matrix
- raw JSON view

XLSX export is available at:

```text
GET /web/batches/{batch_id}/report.xlsx
```

Report generation sets batch status to `DONE`.

## 21. Product Matrix

Product matrix logic lives in `app/services/product_matrix.py`.

Compared aggregate fields:

```text
packages
net_weight
net_weight_with_glaze
net_weight_with_ice
net_weight_with_glaze_and_pack
gross_weight
```

Behavior:

- Only document types whose schema has matching product fields participate.
- Rows are ordered by selected document profile and original batch order.
- The first `PACKING_LIST` acts as the anchor when present.
- Supported values are parsed as decimal sums, including semicolon-separated
  per-row fragments.
- Cell statuses are `anchor`, `match`, `mismatch`, `missing`, or null for
  unsupported fields.

## 22. API Surface

### Public JSON API

Mounted directly on the FastAPI app.

```text
GET  /ping
GET  /batches/
GET  /batches/{batch_id}
POST /batches/
POST /batches/{batch_id}/upload
POST /batches/{batch_id}/process
POST /batches/{batch_id}/confirm-prep
GET  /batches/{batch_id}/review
POST /batches/documents/{doc_id}/fields/{field_key}
POST /batches/{batch_id}/review/complete
GET  /batches/{batch_id}/report
POST /batches/{batch_id}/delete
GET  /archive
GET  /system/status
GET  /files/{path}
```

### Frontend API

Mounted under `/web/api` and used by the React app.

```text
GET  /web/app
GET  /web/app/{path}
POST /web/upload
POST /web/api/batches/{batch_id}/upload
POST /web/api/batches/{batch_id}/confirm-prep
GET  /web/api/doc_types
GET  /web/api/batches
GET  /web/api/batches/{batch_id}
POST /web/api/feedback
POST /web/api/batches/{batch_id}/complete
POST /web/api/documents/{doc_id}/fields/{field_key}/update
POST /web/api/documents/{doc_id}/fields/{field_key}/confirm
POST /web/api/batches/{batch_id}/delete
POST /web/api/documents/{doc_id}/set_type
POST /web/api/documents/{doc_id}/refill
POST /web/api/documents/{doc_id}/rotate
POST /web/api/documents/{doc_id}/delete
GET  /web/batches/{batch_id}/report.xlsx
```

The React API base defaults to `/web`; the JSON API base defaults to
`/web/api`.

## 23. Frontend Experience

The React frontend lives in `test frontend/`.

Routes:

```text
/new
/queue
/resolve/:batchId
/resolve/:batchId/:docIndex
/table/:batchId
/history
/feedback
/feedback/instructions
```

Main screens:

- New packet upload.
- Queue/preparation screen with document previews, profile selection, rotate,
  delete, and confirm.
- Resolve/review screen with document navigation, type selection, refill,
  missing/low-confidence field correction, and preview highlighting.
- Summary table with field matrix, validation matrix, product matrix, preview
  slices, add-documents flow, XLSX export, and links back to review.
- History of previous batches.
- Feedback form.
- Instructions page with embedded demo video.

The legacy Jinja templates still exist but the active richer UI is the React app
served from `/web/app` when `test frontend/dist/index.html` exists.

## 24. Worker and Task Behavior

Celery tasks:

```text
supplyhub.process_batch
supplyhub.process_batch_delta
supplyhub.validate_batch
supplyhub.send_daily_summary
```

Behavior:

- API enqueue functions record active tasks in `Batch.meta.active_tasks`.
- If Celery is unavailable, processing/validation runs as a local async task
  inside the API process.
- Batch deletion cancels local tasks, revokes Celery tasks best effort, clears
  task metadata, deletes DB rows, and removes files.
- Celery beat schedules the daily Telegram summary at 09:00 UTC.

## 25. Blocklist

`app/blocklist.txt` contains regex patterns for document text that should be
dropped during processing. The pipeline evaluates extracted document text after
OCR/classification token flattening. Matching documents are removed with their
raw, derived, and preview assets.

The current blocklist is aimed at removing boilerplate contract pages that do
not need downstream extraction.

## 26. Feedback

Feedback handling lives in `app/services/feedback.py`.

Supported feedback:

- `problem`
- `improvement`

Limits:

- subject: 120 characters
- message: 3500 characters
- contact: 80 characters
- up to 5 files
- each file up to 5 MB
- allowed attachments: PNG, JPG/JPEG, PDF

Tickets are stored under `feedback/pending/{ticket_id}`. If Telegram sending
succeeds, the local pending directory is removed.

## 27. Testing

Current tests:

- `tests/test_document_profiles.py`
- `tests/test_validation_profiles.py`
- `tests/test_product_matrix.py`

Smoke/integration helpers also exist under `test_ocr/` and root-level test
scripts. They are not a complete CI suite.

The current automated test coverage is focused on:

- document profile expected sets
- profile-filtered validation rules
- product matrix ordering, parsing, support detection, and report payload
  persistence

## 28. Implementation Principles

Current implementation principles visible in the code:

- Persist raw source files and derived artifacts on local disk.
- Keep relational metadata in PostgreSQL.
- Keep OCR/filler responses auditable through `ocr.json`, `filled.json`, and
  optional local archive copies.
- Treat LLM output as field candidates, not as a confidence source.
- Keep field history by versioning instead of overwriting rows.
- Make manual user edits authoritative with confidence `1.0`.
- Keep processing resilient with Celery fallback and warning accumulation.
- Recompute validation/report payloads after meaningful user corrections.

## 29. Production Hardening Backlog

Highest-priority hardening items:

1. Add authentication, authorization, and audit logging.
2. Replace direct schema creation with Alembic migrations.
3. Lock down `/files` and avoid serving the whole storage root.
4. Move all secrets and Telegram overrides to environment or a secret manager.
5. Add integration tests for upload, processing, review, validation, report, and
   delete flows.
6. Add structured logs, metrics, tracing, and queue visibility beyond the
   current status snapshot.
7. Add OCR/filler retry policies, request size limits, and model-version
   provenance.
8. Improve confidence scoring with format/anchor/table heuristics or a tested
   model.
9. Normalize frontend source text encoding and settle the product name
   convention (`LOGOS` vs `SupplyHub`).
10. Document supported deployment topologies and required external services.
