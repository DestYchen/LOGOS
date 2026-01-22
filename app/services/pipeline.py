from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from collections import Counter

from celery.app.base import Celery

from app.core.config import get_settings
from app.core.database import get_session
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.core.schema import get_schema
from app.core.storage import batch_dir, unique_filename
from app.models import Batch, Document, FilledField
from sqlalchemy import select
from app.services import (
    blocklist,
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

_CONTRACT_PART_TYPES = {
    DocumentType.CONTRACT_1,
    DocumentType.CONTRACT_2,
    DocumentType.CONTRACT_3,
}
_CONTRACT_PART_ORDER = [
    DocumentType.CONTRACT_1,
    DocumentType.CONTRACT_2,
    DocumentType.CONTRACT_3,
]

_TOKEN_ID_RE = re.compile(r"^p(\d+)_t(.+)$")


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


def _build_document_text(tokens: List[Dict[str, Any]], extraction: Optional[text_extractor.TextExtractionResult]) -> str:
    parts: List[str] = []
    tokens_text = " ".join(token.get("text", "") for token in tokens).strip()
    if tokens_text:
        parts.append(tokens_text)
    if extraction and extraction.text not in parts:
        parts.append(extraction.text)
    return "\n\n".join(parts)


def _is_contract_part(document: Document) -> bool:
    return document.doc_type in _CONTRACT_PART_TYPES


def _load_contract_tokens(paths, document: Document) -> List[Dict[str, Any]]:
    if not document.ocr_path:
        return []
    ocr_file = paths.base / document.ocr_path
    if not ocr_file.exists():
        return []
    try:
        with ocr_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return []
    return classification.flatten_tokens(payload)


def _build_contract_text(paths, document: Document, tokens: List[Dict[str, Any]]) -> str:
    raw_file = paths.raw / document.filename
    extraction = text_extractor.extract_text(raw_file, document.mime)
    tokens_text = " ".join(token.get("text", "") for token in tokens).strip()
    parts: List[str] = []
    if tokens_text:
        parts.append(tokens_text)
    if extraction and extraction.text not in parts:
        parts.append(extraction.text)
    return "\n\n".join(parts)


def _parse_preview_page(path: Path) -> Optional[int]:
    stem = path.stem.lower()
    if stem.startswith("page_"):
        suffix = stem[5:]
        if suffix.isdigit():
            return int(suffix)
    return None


def _load_contract_previews(paths, document: Document) -> List[Tuple[int, Path]]:
    preview_dir = paths.preview / str(document.id)
    if not preview_dir.exists():
        return []
    items: List[Tuple[Optional[int], Path]] = []
    for preview in preview_dir.iterdir():
        if not preview.is_file() or preview.suffix.lower() != ".png":
            continue
        items.append((_parse_preview_page(preview), preview))
    items.sort(key=lambda item: (item[0] is None, item[0] or 0, item[1].name))
    normalized: List[Tuple[int, Path]] = []
    for index, (page_number, preview) in enumerate(items, start=1):
        normalized.append((page_number if page_number else index, preview))
    return normalized


def _token_page_number(token: Dict[str, Any]) -> int:
    raw = token.get("page", 1)
    try:
        page = int(raw)
    except (TypeError, ValueError):
        page = 1
    return page if page > 0 else 1


def _shift_token_id(token_id: Optional[str], new_page: int) -> Optional[str]:
    if not token_id:
        return token_id
    match = _TOKEN_ID_RE.match(str(token_id))
    if not match:
        return token_id
    try:
        page_index = max(new_page - 1, 0)
    except Exception:
        page_index = 0
    suffix = match.group(2)
    return f"p{page_index}_t{suffix}"


def _build_token_page_map(tokens: List[Dict[str, Any]]) -> Dict[str, int]:
    token_page_map: Dict[str, int] = {}
    for token in tokens:
        token_id = token.get("id")
        if token_id is None:
            continue
        token_page_map[str(token_id)] = _token_page_number(token)
    return token_page_map


def _parse_token_ref_page(token_ref: Any) -> Optional[int]:
    if token_ref is None:
        return None
    ref = str(token_ref)
    if not ref:
        return None
    match = _TOKEN_ID_RE.match(ref)
    if not match:
        return None
    try:
        page_index = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if page_index < 0:
        return None
    return page_index + 1


def _derive_page_from_refs(
    token_refs: Any,
    token_page_map: Dict[str, int],
    tokens: List[Dict[str, Any]],
) -> Optional[int]:
    if not token_refs:
        return None
    if not isinstance(token_refs, list):
        token_refs = [token_refs]

    pages: List[int] = []
    for ref in token_refs:
        ref_id = "" if ref is None else str(ref)
        if not ref_id:
            continue
        mapped = token_page_map.get(ref_id)
        if mapped is not None:
            pages.append(mapped)
            continue
        try:
            idx = int(ref_id)
        except (TypeError, ValueError):
            idx = None
        if idx is not None and 0 <= idx < len(tokens):
            pages.append(_token_page_number(tokens[idx]))
            continue
        parsed = _parse_token_ref_page(ref_id)
        if parsed is not None:
            pages.append(parsed)

    if not pages:
        return None
    counts = Counter(pages)
    most_common = counts.most_common()
    if not most_common:
        return None
    top_count = most_common[0][1]
    candidates = [page for page, count in most_common if count == top_count]
    return min(candidates)


def _sync_field_pages(
    fields: Dict[str, Dict[str, Any]],
    tokens: List[Dict[str, Any]],
    *,
    doc_id: Optional[uuid.UUID] = None,
) -> None:
    if not fields or not tokens:
        return
    token_page_map = _build_token_page_map(tokens)
    if not token_page_map:
        return
    for key, payload in fields.items():
        token_refs = payload.get("token_refs")
        derived = _derive_page_from_refs(token_refs, token_page_map, tokens)
        if derived is None:
            continue
        current = payload.get("page")
        try:
            current_page = int(current)
        except (TypeError, ValueError):
            current_page = None
        if current_page != derived:
            payload["page"] = derived
            logger.debug(
                "Adjusted field page from %s to %s for %s (doc=%s)",
                current_page,
                derived,
                key,
                doc_id,
            )


def _contract_page_count(
    document: Document,
    tokens: List[Dict[str, Any]],
    previews: List[Tuple[int, Path]],
) -> int:
    if tokens:
        return max(_token_page_number(token) for token in tokens)
    if document.pages and document.pages > 0:
        return document.pages
    if previews:
        return max(page for page, _ in previews)
    return 1


def _cleanup_document_assets(paths, document: Document) -> None:
    raw_file = paths.raw / document.filename
    try:
        raw_file.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove raw file for %s", document.id, exc_info=True)

    try:
        shutil.rmtree(paths.derived / str(document.id), ignore_errors=True)
    except Exception:
        logger.debug("Failed to remove derived files for %s", document.id, exc_info=True)

    try:
        shutil.rmtree(paths.preview / str(document.id), ignore_errors=True)
    except Exception:
        logger.debug("Failed to remove previews for %s", document.id, exc_info=True)


async def _drop_blocklisted_document(session, batch: Batch, paths, document: Document) -> None:
    _cleanup_document_assets(paths, document)
    if document in batch.documents:
        batch.documents.remove(document)
    await session.delete(document)
    await session.flush()


async def _merge_contract_parts(session, batch: Batch, paths) -> None:
    parts = [doc for doc in batch.documents if _is_contract_part(doc)]
    if not parts:
        return

    parts_by_type: Dict[DocumentType, List[Document]] = {}
    for doc in parts:
        parts_by_type.setdefault(doc.doc_type, []).append(doc)

    if any(len(parts_by_type.get(doc_type, [])) != 1 for doc_type in _CONTRACT_PART_ORDER):
        logger.info("Contract parts incomplete or duplicated for batch %s; skipping merge", batch.id)
        return

    if any(parts_by_type[doc_type][0].status != DocumentStatus.TEXT_READY for doc_type in _CONTRACT_PART_ORDER):
        logger.info("Contract parts not ready for batch %s; skipping merge", batch.id)
        return

    ordered_parts = [parts_by_type[doc_type][0] for doc_type in _CONTRACT_PART_ORDER]
    combined_tokens: List[Dict[str, Any]] = []
    combined_texts: List[str] = []
    part_previews: List[List[Tuple[int, Path]]] = []
    part_page_counts: List[int] = []
    page_offset = 0

    for document in ordered_parts:
        tokens = _load_contract_tokens(paths, document)
        previews = _load_contract_previews(paths, document)
        part_page_count = _contract_page_count(document, tokens, previews)
        part_previews.append(previews)
        part_page_counts.append(part_page_count)
        part_text = _build_contract_text(paths, document, tokens)
        if part_text:
            combined_texts.append(part_text)
        if tokens:
            for token in tokens:
                new_token = dict(token)
                new_page = _token_page_number(token) + page_offset
                new_token["page"] = new_page
                shifted_id = _shift_token_id(token.get("id"), new_page)
                if shifted_id is not None:
                    new_token["id"] = shifted_id
                combined_tokens.append(new_token)
        page_offset += part_page_count

    merged_text = "\n\n".join(text for text in combined_texts if text.strip())
    merged_filename = unique_filename(paths.raw, "contract_merged.txt")
    merged_raw = paths.raw / merged_filename
    merged_raw.write_text(merged_text, encoding="utf-8")

    merged_doc = Document(
        batch_id=batch.id,
        filename=merged_filename,
        mime="text/plain",
        doc_type=DocumentType.CONTRACT,
        status=DocumentStatus.TEXT_READY,
        pages=page_offset,
    )
    batch.documents.append(merged_doc)
    session.add(merged_doc)
    await session.flush()

    derived = paths.derived_for(str(merged_doc.id))
    ocr_file = derived / "ocr.json"
    with ocr_file.open("w", encoding="utf-8") as handle:
        json.dump({"doc_id": str(merged_doc.id), "tokens": combined_tokens}, handle, indent=2)
    merged_doc.ocr_path = str(ocr_file.relative_to(paths.base))

    merged_preview_dir = paths.preview_for(str(merged_doc.id))
    page_offset = 0
    for index, document in enumerate(ordered_parts):
        previews = part_previews[index]
        for page_number, preview in previews:
            target_page = page_offset + page_number
            target_path = merged_preview_dir / f"page_{target_page}.png"
            try:
                shutil.copy2(preview, target_path)
            except Exception:
                logger.debug("Failed to copy contract preview %s", preview, exc_info=True)
        page_offset += part_page_counts[index]

    for document in ordered_parts:
        _cleanup_document_assets(paths, document)
        if document in batch.documents:
            batch.documents.remove(document)
        await session.delete(document)

    await session.flush()


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
            for document in list(batch.documents):
                if batch.status in CANCELLATION_STATUSES:
                    break
                result = await _run_ocr_step(session, batch_id, batch, document)
                if result is not None:
                    ocr_results.append(result)

            await session.flush()
            if await _is_cancelled(batch_id, batch.status):
                return

            await _merge_contract_parts(session, batch, batch_paths)
            if await _is_cancelled(batch_id, batch.status):
                return

            filler_results: List[ProcessingResult] = []
            for document in list(batch.documents):
                if batch.status in CANCELLATION_STATUSES:
                    break
                if document.status == DocumentStatus.TEXT_READY:
                    if document.doc_type in _CONTRACT_PART_TYPES:
                        continue
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


async def _run_ocr_step(session, batch_id: uuid.UUID, batch: Batch, document: Document) -> ProcessingResult | None:
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

    # Derive page count from tokens (max page index), fallback to 1 if any tokens
    try:
        max_page = max(int(t.get('page', 1)) for t in tokens) if tokens else 0
    except Exception:
        max_page = 1 if tokens else 0

    if not tokens:
        logger.warning('No OCR tokens extracted for %s', document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: OCR не дал токенов.",
        )

    doc_text = _build_document_text(tokens, extraction)
    if blocklist.should_drop(doc_text):
        logger.info("Dropping document %s due to blocklist match", document.filename)
        await _drop_blocklisted_document(session, batch, paths, document)
        return None

    document.ocr_path = str(ocr_file.relative_to(paths.base))
    document.pages = max_page

    doc_type = classification.classify_document(tokens, file_name=document.filename)
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

    _sync_field_pages(scored_fields, tokens, doc_id=document.id)

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
    # Avoid lazy-loading in async context; fetch explicitly.
    result = await session.execute(
        select(FilledField).where(FilledField.doc_id == document.id)
    )
    existing = result.scalars().all()

    existing_versions: Dict[str, int] = {}
    for field in existing:
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

    _sync_field_pages(scored_fields, tokens, doc_id=document.id)

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

