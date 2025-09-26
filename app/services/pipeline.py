from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from celery.app.base import Celery

from app.core.config import get_settings
from app.core.database import get_session
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.core.schema import get_schema
from app.core.storage import batch_dir
from app.models import Document, FilledField
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
from app.workers.celery_app import celery_app

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    document: Document
    success: bool
    message: str | None = None


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
    async with get_session() as session:
        batch = await batch_service.get_batch(session, batch_id)
        if batch is None:
            return
        batch_paths = batch_dir(str(batch_id))
        batch_paths.ensure()
        results: List[ProcessingResult] = []
        for document in batch.documents:
            result = await _process_document(session, batch_id, document)
            results.append(result)
        failures = [result for result in results if not result.success]
        if failures:
            meta = dict(batch.meta) if batch.meta else {}
            warnings = list(meta.get('processing_warnings', []))
            for failure in failures:
                message = failure.message or f"Документ {failure.document.filename} не обработан."
                if message not in warnings:
                    warnings.append(message)
            meta['processing_warnings'] = warnings
            batch.meta = meta
        elif batch.meta and 'processing_warnings' in batch.meta:
            meta = dict(batch.meta)
            meta.pop('processing_warnings', None)
            batch.meta = meta
        if results and all(not result.success for result in results):
            batch.status = BatchStatus.FAILED
        else:
            batch.status = BatchStatus.FILLED_AUTO
        await session.flush()
        await status.record_snapshot(
            session,
            workers_busy=0,
            workers_total=0,
            queue_depth=0,
            active_batches=1,
            active_docs=len(batch.documents),
        )


async def _process_document(session, batch_id: uuid.UUID, document: Document) -> ProcessingResult:
    paths = batch_dir(str(batch_id))
    raw_file = paths.raw / document.filename
    if not raw_file.exists():
        raise FileNotFoundError(f"raw file missing: {raw_file}")

    extraction = text_extractor.extract_text(raw_file, document.mime)
    needs_ocr = text_extractor.requires_ocr(raw_file, document.mime)

    derived = paths.derived_for(str(document.id))
    ocr_file = derived / 'ocr.json'

    if not needs_ocr and extraction is not None:
        ocr_payload = {'doc_id': str(document.id), 'tokens': []}
    else:
        if not needs_ocr and extraction is None:
            logger.warning('Parser extraction unavailable for %s, running OCR fallback', raw_file)
        ocr_payload = await ocr.run_ocr(document.id, raw_file, file_name=document.filename)

    with ocr_file.open('w', encoding='utf-8') as handle:
        json.dump(ocr_payload, handle, indent=2)

    tokens = classification.flatten_tokens(ocr_payload)
    if not tokens and extraction is not None:
        tokens = _plain_text_tokens(extraction.text)

    document.ocr_path = str(ocr_file.relative_to(paths.base))
    document.pages = 1 if tokens else 0

    if not tokens:
        logger.warning('No OCR tokens extracted for %s', document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: OCR не вернул текст.",
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

    filled_response = await json_filler.fill_json(
        document.id,
        doc_type,
        doc_text=doc_text,
        file_name=document.filename,
        ocr_tokens=filler_tokens or None,
    )

    fields_raw = filled_response.get('fields', {})
    normalized_fields = _flatten_filler_fields(fields_raw)
    scored_fields: Dict[str, Dict[str, Any]] = {}
    for key, payload in normalized_fields.items():
        payload = dict(payload)  # work with a copy to avoid mutating original
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
            message=f"Документ {document.filename} не содержит заполненных полей после обработки.",
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


async def run_validation_pipeline(batch_id: uuid.UUID) -> None:
    async with get_session() as session:
        batch = await batch_service.get_batch(session, batch_id)
        if batch is None:
            return
        messages = await validation.validate_batch(session, batch_id)
        await validation.store_validations(session, batch_id, messages)
        batch.status = BatchStatus.VALIDATED
        await reporting.generate_report(session, batch_id)
        await status.record_snapshot(
            session,
            workers_busy=0,
            workers_total=0,
            queue_depth=0,
            active_batches=0,
            active_docs=0,
        )


async def enqueue_batch_processing(batch_id: uuid.UUID) -> str:
    try:
        result = _celery().send_task("supplyhub.process_batch", args=[str(batch_id)])
        return result.id
    except Exception:
        asyncio.create_task(run_batch_pipeline(batch_id))
        return f"local-{batch_id}"


async def enqueue_validation(batch_id: uuid.UUID) -> str:
    try:
        result = _celery().send_task("supplyhub.validate_batch", args=[str(batch_id)])
        return result.id
    except Exception:
        asyncio.create_task(run_validation_pipeline(batch_id))
        return f"local-validate-{batch_id}"
