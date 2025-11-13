from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List

from celery.app.base import Celery

from app.core.config import get_settings
from app.core.database import get_session
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.core.schema import get_schema
from app.core.storage import batch_dir
from app.models import Batch, Document, FilledField
from app.services import (
    classification,
    confidence,
    json_filler,
    ocr,
    reporting,
    status,
    text_extractor,
    validation,
)
from app.services import batches as batch_service
from app.services import tasks as task_tracker
from app.workers.celery_app import celery_app

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    document: Document
    success: bool
    message: str | None = None


CANCELLATION_STATUSES = {BatchStatus.CANCEL_REQUESTED, BatchStatus.CANCELLED}


@dataclass
class _LocalTaskInfo:
    kind: str
    task: asyncio.Task


_LOCAL_TASKS: Dict[uuid.UUID, Dict[str, _LocalTaskInfo]] = {}


def _register_local_task(batch_id: uuid.UUID, *, task_id: str, kind: str, task: asyncio.Task) -> None:
    bucket = _LOCAL_TASKS.setdefault(batch_id, {})
    bucket[task_id] = _LocalTaskInfo(kind=kind, task=task)

    def _cleanup(_task: asyncio.Task) -> None:
        _deregister_local_task(batch_id, task_id)

    task.add_done_callback(_cleanup)


def _deregister_local_task(batch_id: uuid.UUID, task_id: str) -> None:
    bucket = _LOCAL_TASKS.get(batch_id)
    if not bucket:
        return
    bucket.pop(task_id, None)
    if not bucket:
        _LOCAL_TASKS.pop(batch_id, None)


async def cancel_local_tasks(batch_id: uuid.UUID) -> None:
    bucket = _LOCAL_TASKS.get(batch_id)
    if not bucket:
        return
    entries = list(bucket.items())
    for _, info in entries:
        if not info.task.done():
            info.task.cancel()
    await asyncio.gather(*(info.task for _, info in entries), return_exceptions=True)


async def _start_local_task(
    batch_id: uuid.UUID,
    *,
    kind: str,
    runner: Callable[[uuid.UUID], Awaitable[None]],
) -> str:
    task_id = f"local-{kind}-{uuid.uuid4()}"
    try:
        await task_tracker.record_task(batch_id, kind=kind, transport="local", task_id=task_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - best effort bookkeeping
        logger.exception("Failed to record local %s task for batch %s", kind, batch_id)

    async def _runner() -> None:
        try:
            await runner(batch_id)
        except asyncio.CancelledError:
            logger.info("%s task cancelled for batch %s", kind, batch_id)
            raise
        finally:
            await task_tracker.remove_task(batch_id, kind=kind, task_id=task_id)

    task = asyncio.create_task(_runner(), name=f"{kind}-{batch_id}")
    _register_local_task(batch_id, task_id=task_id, kind=kind, task=task)
    return task_id


async def _is_cancelled(batch_id: uuid.UUID, status: BatchStatus) -> bool:
    if status in CANCELLATION_STATUSES:
        return True
    async with get_session() as session:
        fresh = await session.get(Batch, batch_id)
        if fresh is None:
            return True
        return fresh.status in CANCELLATION_STATUSES


def _celery() -> Celery:
    return celery_app


def _flatten_filler_fields(data: Dict[str, Any], prefix: str = "") -> Dict[str, Dict[str, Any]]:
    """Normalize nested json-filler response into flat field mapping."""

    flattened: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            if "value" in value:
                flattened[full_key] = value
            else:
                flattened.update(_flatten_filler_fields(value, full_key))
        else:
            flattened[full_key] = {"value": value}
    return flattened


def _plain_text_tokens(raw_text: str) -> List[Dict[str, Any]]:
    stripped = raw_text.strip()
    if not stripped:
        return []
    return [
        {
            "id": "plain_text",
            "text": stripped,
            "conf": 1.0,
            "bbox": [0, 0, 0, 0],
            "page": 1,
            "category": "Text",
        }
    ]


async def run_batch_pipeline(batch_id: uuid.UUID) -> None:
    auto_validate = False
    try:
        async with get_session() as session:
            batch = await batch_service.get_batch(session, batch_id)
            if batch is None:
                return
            if batch.status in CANCELLATION_STATUSES:
                logger.info("Skipping processing for cancelled batch %s", batch_id)
                return
            batch_paths = batch_dir(str(batch_id))
            batch_paths.ensure()

            ocr_results: List[ProcessingResult] = []
            for document in batch.documents:
                if batch.status in CANCELLATION_STATUSES:
                    break
                result = await _run_ocr_step(session, batch_id, document)
                ocr_results.append(result)

            await session.flush()
            if await _is_cancelled(batch_id, batch.status):
                return

            filler_results: List[ProcessingResult] = []
            for document in batch.documents:
                if batch.status in CANCELLATION_STATUSES:
                    break
                if document.status == DocumentStatus.TEXT_READY:
                    result = await _run_filler_step(session, batch_id, document)
                    filler_results.append(result)

            await session.flush()
            if await _is_cancelled(batch_id, batch.status):
                return

            results = ocr_results + filler_results
            failures = [result for result in results if not result.success]
            if failures:
                meta = dict(batch.meta) if batch.meta else {}
                warnings = list(meta.get("processing_warnings", []))
                for failure in failures:
                    message = failure.message or f"Документ {failure.document.filename} не обработан."
                    if message not in warnings:
                        warnings.append(message)
                meta["processing_warnings"] = warnings
                batch.meta = meta
            elif batch.meta and "processing_warnings" in batch.meta:
                meta = dict(batch.meta)
                meta.pop("processing_warnings", None)
                batch.meta = meta

            if await _is_cancelled(batch_id, batch.status):
                return
            if batch.status not in CANCELLATION_STATUSES:
                if batch.documents and all(doc.status == DocumentStatus.FAILED for doc in batch.documents):
                    batch.status = BatchStatus.FAILED
                else:
                    batch.status = BatchStatus.FILLED_AUTO

            await session.flush()
            if batch.status not in CANCELLATION_STATUSES:
                await status.record_snapshot(
                    session,
                    workers_busy=0,
                    workers_total=0,
                    queue_depth=0,
                    active_batches=1,
                    active_docs=len(batch.documents),
                )
            if batch.status not in CANCELLATION_STATUSES and batch.status != BatchStatus.FAILED:
                auto_validate = True
    except asyncio.CancelledError:
        logger.info("Batch pipeline cancelled for %s", batch_id)
        raise
    finally:
        await task_tracker.remove_task(batch_id, kind="process")

    if auto_validate:
        try:
            await run_validation_pipeline(batch_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic validation failed for batch %s", batch_id)


async def _run_ocr_step(session, batch_id: uuid.UUID, document: Document) -> ProcessingResult:
    paths = batch_dir(str(batch_id))
    raw_file = paths.raw / document.filename
    if not raw_file.exists():
        raise FileNotFoundError(f"raw file missing: {raw_file}")

    document.filled_path = None
    document.ocr_path = None

    extraction = text_extractor.extract_text(raw_file, document.mime)
    needs_ocr = text_extractor.requires_ocr(raw_file, document.mime)

    derived = paths.derived_for(str(document.id))
    ocr_file = derived / 'ocr.json'

    if not needs_ocr and extraction is not None:
        ocr_payload: Dict[str, Any] = {'doc_id': str(document.id), 'tokens': []}
    else:
        if not needs_ocr and extraction is None:
            logger.warning('Parser extraction unavailable for %s, running OCR fallback', raw_file)
        try:
            ocr_payload = await ocr.run_ocr(document.id, raw_file, file_name=document.filename)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error('OCR service failed for %s', document.filename, exc_info=True)
            document.status = DocumentStatus.FAILED
            document.filled_path = None
            return ProcessingResult(
                document=document,
                success=False,
                message=f"Документ {document.filename} не обработан: ошибка вызова OCR. Обратитесь к администратору.",
            )

    with ocr_file.open('w', encoding='utf-8') as handle:
        json.dump(ocr_payload, handle, indent=2)

    tokens = classification.flatten_tokens(ocr_payload)
    if not tokens and extraction is not None:
        tokens = _plain_text_tokens(extraction.text)

    document.ocr_path = str(ocr_file.relative_to(paths.base))
    # Derive page count from tokens (max page index), fallback to 1 if any tokens
    try:
        max_page = max(int(t.get('page', 1)) for t in tokens) if tokens else 0
    except Exception:
        max_page = 1 if tokens else 0
    document.pages = max_page

    if not tokens:
        logger.warning('No OCR tokens extracted for %s', document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: OCR не дал токенов.",
        )

    doc_type = classification.classify_document(tokens)
    if doc_type == DocumentType.UNKNOWN:
        logger.info('Document %s classification is UNKNOWN; skipping', document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: тип не распознан.",
        )

    document.doc_type = doc_type
    document.status = DocumentStatus.TEXT_READY
    return ProcessingResult(document=document, success=True, message=None)


async def _run_filler_step(session, batch_id: uuid.UUID, document: Document) -> ProcessingResult:
    paths = batch_dir(str(batch_id))
    raw_file = paths.raw / document.filename
    derived = paths.derived_for(str(document.id))

    doc_type = document.doc_type
    if doc_type == DocumentType.UNKNOWN:
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: тип не распознан.",
        )

    tokens: List[Dict[str, Any]] = []
    if document.ocr_path:
        ocr_file = paths.base / document.ocr_path
        if ocr_file.exists():
            try:
                with ocr_file.open('r', encoding='utf-8') as handle:
                    ocr_payload = json.load(handle)
                tokens = classification.flatten_tokens(ocr_payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                tokens = []

    extraction = text_extractor.extract_text(raw_file, document.mime)
    if not tokens and extraction is not None and extraction.text.strip():
        tokens = _plain_text_tokens(extraction.text)

    if not tokens:
        logger.warning('No OCR tokens available for filler step %s', document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: OCR не дал токенов.",
        )

    schema = get_schema(doc_type)

    doc_text_parts: List[str] = []
    tokens_text = ' '.join(token.get('text', '') for token in tokens).strip()
    if tokens_text:
        doc_text_parts.append(tokens_text)
    if extraction and extraction.text not in doc_text_parts:
        doc_text_parts.append(extraction.text)
    doc_text = '\n\n'.join(doc_text_parts)

    filler_tokens = [
        {key: value for key, value in token.items() if key != 'category'}
        for token in tokens
    ]

    try:
        filled_response = await json_filler.fill_json(
            document.id,
            doc_type,
            doc_text=doc_text,
            file_name=document.filename,
            ocr_tokens=filler_tokens or None,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error('JSON filler service failed for %s', document.filename, exc_info=True)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: ошибка вызова JSON Filler. Обратитесь к администратору.",
        )

    fields_raw = filled_response.get('fields', {})
    normalized_fields = _flatten_filler_fields(fields_raw)
    scored_fields: Dict[str, Dict[str, Any]] = {}
    for key, payload in normalized_fields.items():
        payload = dict(payload)
        payload.setdefault('bbox', [])
        payload.setdefault('token_refs', None)
        payload.setdefault('source', 'llm')
        score = confidence.score_field(key, payload, tokens, schema)
        payload['confidence'] = score
        scored_fields[key] = payload

    filled_file = derived / 'filled.json'
    with filled_file.open('w', encoding='utf-8') as handle:
        json.dump({'fields': scored_fields}, handle, indent=2)

    await _store_fields(session, document, scored_fields)

    if not scored_fields:
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        try:
            filled_file.unlink(missing_ok=True)
        except TypeError:  # pragma: no cover - compatibility
            if filled_file.exists():
                filled_file.unlink()
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не содержит заполненных полей после проверки.",
        )

    document.status = DocumentStatus.FILLED_AUTO
    document.filled_path = str(filled_file.relative_to(paths.base))
    return ProcessingResult(document=document, success=True, message=None)

async def _store_fields(session, document: Document, fields: Dict[str, Dict[str, Any]]) -> None:
    existing_versions: Dict[str, int] = {}
    for field in document.fields:
        if field.field_key in fields and field.latest:
            field.latest = False
        existing_versions[field.field_key] = max(existing_versions.get(field.field_key, 0), field.version)

    for key, payload in fields.items():
        value = payload.get("value")
        bbox = payload.get("bbox")
        token_refs = payload.get("token_refs")
        page = payload.get("page")
        confidence_score = float(payload.get("confidence", 0.0))
        source = payload.get("source", "llm")
        version = existing_versions.get(key, 0) + 1
        field = FilledField(
            doc_id=document.id,
            field_key=key,
            value=value,
            page=page,
            bbox=bbox,
            token_refs=token_refs,
            confidence=confidence_score,
            source=source,
            version=version,
            latest=True,
        )
        session.add(field)

    await session.flush()


async def _append_processing_warning(session, batch_id: uuid.UUID, message: str) -> None:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        return
    meta = dict(batch.meta) if batch.meta else {}
    warnings = list(meta.get("processing_warnings", []))
    if message not in warnings:
        warnings.append(message)
    meta["processing_warnings"] = warnings
    batch.meta = meta
    await session.flush()


async def fill_document_from_existing_ocr(
    session, *, batch_id: uuid.UUID, document: Document, forced_doc_type: DocumentType
) -> None:
    """Fill fields for an already OCR-processed document with a user-selected type.

    Loads tokens from saved OCR payload, reconstructs text, calls JSON filler for the
    provided document type, and persists fields and artifacts. Does not re-run OCR.
    """
    paths = batch_dir(str(batch_id))
    # Load OCR payload
    tokens: List[Dict[str, Any]] = []
    if document.ocr_path:
        ocr_file = paths.base / document.ocr_path
        if ocr_file.exists():
            try:
                with ocr_file.open("r", encoding="utf-8") as handle:
                    ocr_payload = json.load(handle)
                tokens = classification.flatten_tokens(ocr_payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                tokens = []

    # Fallback to plain text if needed (for non-image docs)
    if not tokens:
        raw_file = paths.raw / document.filename
        extraction = text_extractor.extract_text(raw_file, document.mime)
        if extraction is not None and extraction.text.strip():
            tokens = _plain_text_tokens(extraction.text)

    document.pages = 1 if tokens else 0

    # Prepare text for JSON filler
    doc_text_parts: List[str] = []
    tokens_text = " ".join(token.get("text", "") for token in tokens).strip()
    if tokens_text:
        doc_text_parts.append(tokens_text)
    raw_file = paths.raw / document.filename
    extraction = text_extractor.extract_text(raw_file, document.mime)
    if extraction and extraction.text not in doc_text_parts:
        doc_text_parts.append(extraction.text)
    doc_text = "\n\n".join(doc_text_parts)

    filler_tokens = [
        {key: value for key, value in token.items() if key != "category"}
        for token in tokens
    ]

    # Call JSON filler
    try:
        filled_response = await json_filler.fill_json(
            document.id,
            forced_doc_type,
            doc_text=doc_text,
            file_name=document.filename,
            ocr_tokens=filler_tokens or None,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error('JSON filler service failed for %s (manual type set)', document.filename, exc_info=True)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        await _append_processing_warning(
            session,
            batch_id,
            f"Документ {document.filename} не обработан: ошибка сервиса JSON Filler. Обратитесь к разработчику.",
        )
        return

    fields_raw = filled_response.get("fields", {})
    normalized_fields = _flatten_filler_fields(fields_raw)
    scored_fields: Dict[str, Dict[str, Any]] = {}
    schema = get_schema(forced_doc_type)
    for key, payload in normalized_fields.items():
        payload = dict(payload)
        payload.setdefault("bbox", [])
        payload.setdefault("token_refs", None)
        payload.setdefault("source", "llm")
        score = confidence.score_field(key, payload, tokens, schema)
        payload["confidence"] = score
        scored_fields[key] = payload

    derived = paths.derived_for(str(document.id))
    filled_file = derived / "filled.json"
    with filled_file.open("w", encoding="utf-8") as handle:
        json.dump({"fields": scored_fields}, handle, indent=2)

    await _store_fields(session, document, scored_fields)
    document.doc_type = forced_doc_type
    document.status = DocumentStatus.FILLED_AUTO
    document.filled_path = str(filled_file.relative_to(paths.base))


async def run_validation_pipeline(batch_id: uuid.UUID) -> None:
    try:
        async with get_session() as session:
            batch = await batch_service.get_batch(session, batch_id)
            if batch is None:
                return
            if await _is_cancelled(batch_id, batch.status):
                return
            messages = await validation.validate_batch(session, batch_id)
            if await _is_cancelled(batch_id, batch.status):
                return
            await validation.store_validations(session, batch_id, messages)
            if await _is_cancelled(batch_id, batch.status):
                return
            if batch.status not in CANCELLATION_STATUSES:
                batch.status = BatchStatus.VALIDATED
            if await _is_cancelled(batch_id, batch.status):
                return
            await reporting.generate_report(session, batch_id)
            if batch.status not in CANCELLATION_STATUSES:
                await status.record_snapshot(
                    session,
                    workers_busy=0,
                    workers_total=0,
                    queue_depth=0,
                    active_batches=0,
                    active_docs=0,
                )
    except asyncio.CancelledError:
        logger.info("Validation pipeline cancelled for %s", batch_id)
        raise
    finally:
        await task_tracker.remove_task(batch_id, kind="validation")


async def enqueue_batch_processing(batch_id: uuid.UUID) -> str:
    try:
        result = _celery().send_task("supplyhub.process_batch", args=[str(batch_id)])
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Celery unavailable, running batch %s locally", batch_id, exc_info=True)
        return await _start_local_task(batch_id, kind="process", runner=run_batch_pipeline)
    else:
        await task_tracker.record_task(batch_id, kind="process", transport="celery", task_id=result.id)
        return result.id


async def enqueue_validation(batch_id: uuid.UUID) -> str:
    try:
        result = _celery().send_task("supplyhub.validate_batch", args=[str(batch_id)])
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Celery unavailable for validation of batch %s, running locally", batch_id, exc_info=True)
        return await _start_local_task(batch_id, kind="validation", runner=run_validation_pipeline)
    else:
        await task_tracker.record_task(batch_id, kind="validation", transport="celery", task_id=result.id)
        return result.id

