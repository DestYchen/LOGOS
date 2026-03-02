from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from app.core.config import get_settings
from app.core.database import get_session
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.core.schema import get_schema
from app.core.storage import batch_dir
from app.models import Batch, Document
from app.services import (
    batches as batch_service,
    classification,
    confidence,
    json_filler_remote,
    json_filler_router,
    local_archive,
    status,
    text_extractor,
)
from app.services import tasks as task_tracker
from app.services import pipeline as base_pipeline

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class RemoteFillInput:
    batch_id: uuid.UUID
    batch_title: str | None
    doc_id: uuid.UUID
    doc_type: DocumentType
    file_name: str
    doc_text: str
    filler_tokens: List[Dict[str, Any]]
    tokens: List[Dict[str, Any]]


@dataclass
class RemoteFillResult:
    doc_id: uuid.UUID
    doc_type: DocumentType
    file_name: str
    tokens: List[Dict[str, Any]]
    fields: Dict[str, Dict[str, Any]]


async def _prepare_remote_input(
    session,
    batch_id: uuid.UUID,
    document: Document,
) -> RemoteFillInput | base_pipeline.ProcessingResult:
    if document.doc_type == DocumentType.UNKNOWN:
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return base_pipeline.ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: тип не распознан.",
        )

    paths = batch_dir(str(batch_id))
    raw_file = paths.raw / document.filename

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

    extraction = text_extractor.extract_text(raw_file, document.mime)
    if not tokens and extraction is not None and extraction.text.strip():
        tokens = base_pipeline._plain_text_tokens(extraction.text)

    if not tokens:
        logger.warning("No OCR tokens available for remote filler step %s", document.filename)
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        return base_pipeline.ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не обработан: OCR не дал токенов.",
        )

    doc_text_parts: List[str] = []
    tokens_text = " ".join(token.get("text", "") for token in tokens).strip()
    if tokens_text:
        doc_text_parts.append(tokens_text)
    if extraction and extraction.text not in doc_text_parts:
        doc_text_parts.append(extraction.text)
    doc_text = "\n\n".join(doc_text_parts)

    filler_tokens = [
        {key: value for key, value in token.items() if key != "category"}
        for token in tokens
    ]
    archive_batch_title = None
    if local_archive.enabled():
        batch = await session.get(Batch, batch_id)
        if batch is not None:
            archive_batch_title = batch_service.extract_batch_title(batch)

    return RemoteFillInput(
        batch_id=batch_id,
        batch_title=archive_batch_title,
        doc_id=document.id,
        doc_type=document.doc_type,
        file_name=document.filename,
        doc_text=doc_text,
        filler_tokens=filler_tokens,
        tokens=tokens,
    )


async def _run_remote_fill(input_data: RemoteFillInput, semaphore: asyncio.Semaphore) -> RemoteFillResult:
    async with semaphore:
        if local_archive.enabled():
            local_archive.write_filler_request(
                batch_id=str(input_data.batch_id),
                batch_title=input_data.batch_title,
                doc_id=str(input_data.doc_id),
                doc_type=input_data.doc_type,
                file_name=input_data.file_name,
                doc_text=input_data.doc_text,
                ocr_tokens=input_data.filler_tokens or None,
                source="initial",
            )
        filled_response = await json_filler_router.fill_json(
            input_data.doc_id,
            input_data.doc_type,
            doc_text=input_data.doc_text,
            file_name=input_data.file_name,
            ocr_tokens=input_data.filler_tokens or None,
        )
        if local_archive.enabled():
            local_archive.write_filler_response(
                batch_id=str(input_data.batch_id),
                batch_title=input_data.batch_title,
                doc_id=str(input_data.doc_id),
                doc_type=input_data.doc_type,
                file_name=input_data.file_name,
                response=filled_response,
                source="initial",
            )

    fields_raw = filled_response.get("fields", {})
    normalized_fields = base_pipeline._flatten_filler_fields(fields_raw)
    schema = get_schema(input_data.doc_type)

    scored_fields: Dict[str, Dict[str, Any]] = {}
    for key, payload in normalized_fields.items():
        payload = dict(payload)
        payload.setdefault("bbox", [])
        payload.setdefault("token_refs", None)
        payload.setdefault("source", "llm")
        score = confidence.score_field(key, payload, input_data.tokens, schema)
        payload["confidence"] = score
        scored_fields[key] = payload

    base_pipeline._sync_field_pages(scored_fields, input_data.tokens, doc_id=input_data.doc_id)
    base_pipeline._apply_vet_cert_date_page_override(scored_fields, input_data.tokens, input_data.doc_type)
    base_pipeline._sync_field_bboxes(scored_fields, input_data.tokens)

    return RemoteFillResult(
        doc_id=input_data.doc_id,
        doc_type=input_data.doc_type,
        file_name=input_data.file_name,
        tokens=input_data.tokens,
        fields=scored_fields,
    )


async def _apply_remote_result(
    session,
    batch_id: uuid.UUID,
    result: RemoteFillResult,
) -> base_pipeline.ProcessingResult:
    document = await session.get(Document, result.doc_id)
    if document is None:
        fallback = Document(
            id=result.doc_id,
            batch_id=batch_id,
            filename=result.file_name,
            doc_type=DocumentType.UNKNOWN,
            status=DocumentStatus.FAILED,
        )
        return base_pipeline.ProcessingResult(
            document=fallback,
            success=False,
            message=f"Документ {result.file_name} не найден при записи результата.",
        )

    paths = batch_dir(str(batch_id))
    derived = paths.derived_for(str(document.id))
    filled_file = derived / "filled.json"

    with filled_file.open("w", encoding="utf-8") as handle:
        json.dump({"fields": result.fields}, handle, indent=2)

    await base_pipeline._store_fields(session, document, result.fields)

    if not result.fields:
        document.status = DocumentStatus.FAILED
        document.filled_path = None
        try:
            filled_file.unlink(missing_ok=True)
        except TypeError:  # pragma: no cover - compatibility
            if filled_file.exists():
                filled_file.unlink()
        return base_pipeline.ProcessingResult(
            document=document,
            success=False,
            message=f"Документ {document.filename} не содержит заполненных полей после проверки.",
        )

    document.status = DocumentStatus.FILLED_AUTO
    document.filled_path = str(filled_file.relative_to(paths.base))
    return base_pipeline.ProcessingResult(document=document, success=True, message=None)


async def run_batch_pipeline_parallel(batch_id: uuid.UUID) -> None:
    auto_validate = False
    try:
        async with get_session() as session:
            batch = await batch_service.get_batch(session, batch_id)
            if batch is None:
                return
            if batch.status in base_pipeline.CANCELLATION_STATUSES:
                logger.info("Skipping processing for cancelled batch %s", batch_id)
                return
            if not base_pipeline._prep_complete(batch):
                logger.info("Skipping processing for batch %s: prep not complete", batch_id)
                return

            batch_paths = batch_dir(str(batch_id))
            batch_paths.ensure()

            progress_enabled = base_pipeline._progress_tracking_enabled(batch)

            ocr_results: List[base_pipeline.ProcessingResult] = []
            for document in list(batch.documents):
                if batch.status in base_pipeline.CANCELLATION_STATUSES:
                    break
                result = await base_pipeline._run_ocr_step(session, batch_id, batch, document)
                if result is not None:
                    ocr_results.append(result)
                if progress_enabled:
                    await session.commit()

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            await base_pipeline._merge_contract_parts(session, batch, batch_paths)
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return
            await base_pipeline._merge_veterinary_certificate_parts(session, batch, batch_paths)
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            remote_types = json_filler_router.remote_doc_types()
            remote_inputs: List[RemoteFillInput] = []
            filler_results: List[base_pipeline.ProcessingResult] = []
            local_docs: List[Document] = []

            for document in list(batch.documents):
                if document.status != DocumentStatus.TEXT_READY:
                    continue
                if document.doc_type in base_pipeline._CONTRACT_PART_TYPES:
                    continue
                if document.doc_type in remote_types:
                    prepared = await _prepare_remote_input(session, batch_id, document)
                    if isinstance(prepared, base_pipeline.ProcessingResult):
                        filler_results.append(prepared)
                        if progress_enabled:
                            await session.commit()
                        continue
                    remote_inputs.append(prepared)
                else:
                    local_docs.append(document)

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            semaphore = asyncio.Semaphore(max(1, settings.remote_json_filler_concurrency))
            remote_tasks = [
                asyncio.create_task(_run_remote_fill(input_data, semaphore))
                for input_data in remote_inputs
            ]

            for document in local_docs:
                if batch.status in base_pipeline.CANCELLATION_STATUSES:
                    break
                result = await base_pipeline._run_filler_step(session, batch_id, document)
                filler_results.append(result)
                if progress_enabled:
                    await session.commit()

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                for task in remote_tasks:
                    task.cancel()
                await asyncio.gather(*remote_tasks, return_exceptions=True)
                return

            for task in asyncio.as_completed(remote_tasks):
                try:
                    remote_result = await task
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.error("Remote filler task failed", exc_info=True)
                    continue
                applied = await _apply_remote_result(session, batch_id, remote_result)
                filler_results.append(applied)
                if progress_enabled:
                    await session.commit()

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
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

            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            if batch.status not in base_pipeline.CANCELLATION_STATUSES:
                if batch.documents and all(doc.status == DocumentStatus.FAILED for doc in batch.documents):
                    batch.status = BatchStatus.FAILED
                else:
                    batch.status = BatchStatus.FILLED_AUTO

            await session.flush()
            if batch.status not in base_pipeline.CANCELLATION_STATUSES:
                await status.record_snapshot(
                    session,
                    workers_busy=0,
                    workers_total=0,
                    queue_depth=0,
                    active_batches=1,
                    active_docs=len(batch.documents),
                )
            if batch.status not in base_pipeline.CANCELLATION_STATUSES and batch.status != BatchStatus.FAILED:
                auto_validate = True
    except asyncio.CancelledError:
        logger.info("Batch pipeline cancelled for %s", batch_id)
        raise
    finally:
        await task_tracker.remove_task(batch_id, kind="process")

    if auto_validate:
        try:
            await base_pipeline.run_validation_pipeline(batch_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic validation failed for batch %s", batch_id)


async def run_batch_delta_pipeline_parallel(batch_id: uuid.UUID) -> None:
    auto_validate = False
    try:
        async with get_session() as session:
            batch = await batch_service.get_batch(session, batch_id)
            if batch is None:
                return
            if batch.status in base_pipeline.CANCELLATION_STATUSES:
                logger.info("Skipping delta processing for cancelled batch %s", batch_id)
                return
            if not base_pipeline._prep_complete(batch):
                logger.info("Skipping delta processing for batch %s: prep not complete", batch_id)
                return

            batch_paths = batch_dir(str(batch_id))
            batch_paths.ensure()

            new_documents = [doc for doc in list(batch.documents) if doc.status == DocumentStatus.NEW]
            if not new_documents:
                return

            ocr_results: List[base_pipeline.ProcessingResult] = []
            for document in new_documents:
                if batch.status in base_pipeline.CANCELLATION_STATUSES:
                    break
                result = await base_pipeline._run_ocr_step(session, batch_id, batch, document)
                if result is None:
                    continue
                if document.status == DocumentStatus.TEXT_READY and (
                    document.doc_type in base_pipeline._CONTRACT_PART_TYPES or document.doc_type == DocumentType.CONTRACT
                ):
                    document.status = DocumentStatus.FAILED
                    document.filled_path = None
                    result = base_pipeline.ProcessingResult(
                        document=document,
                        success=False,
                        message=(
                            f"Документ {document.filename} не обработан: "
                            "добавление контрактов в готовый пакет не поддерживается."
                        ),
                    )
                ocr_results.append(result)

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            remote_types = json_filler_router.remote_doc_types()
            remote_inputs: List[RemoteFillInput] = []
            filler_results: List[base_pipeline.ProcessingResult] = []
            local_docs: List[Document] = []

            for document in new_documents:
                if document.status != DocumentStatus.TEXT_READY:
                    continue
                if document.doc_type in base_pipeline._CONTRACT_PART_TYPES:
                    continue
                if document.doc_type in remote_types:
                    prepared = await _prepare_remote_input(session, batch_id, document)
                    if isinstance(prepared, base_pipeline.ProcessingResult):
                        filler_results.append(prepared)
                        continue
                    remote_inputs.append(prepared)
                else:
                    local_docs.append(document)

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            semaphore = asyncio.Semaphore(max(1, settings.remote_json_filler_concurrency))
            remote_tasks = [
                asyncio.create_task(_run_remote_fill(input_data, semaphore))
                for input_data in remote_inputs
            ]

            for document in local_docs:
                if batch.status in base_pipeline.CANCELLATION_STATUSES:
                    break
                result = await base_pipeline._run_filler_step(session, batch_id, document)
                filler_results.append(result)

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
                for task in remote_tasks:
                    task.cancel()
                await asyncio.gather(*remote_tasks, return_exceptions=True)
                return

            for task in asyncio.as_completed(remote_tasks):
                try:
                    remote_result = await task
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.error("Remote filler task failed (delta)", exc_info=True)
                    continue
                applied = await _apply_remote_result(session, batch_id, remote_result)
                filler_results.append(applied)

            await session.flush()
            if await base_pipeline._is_cancelled(batch_id, batch.status):
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

            if await base_pipeline._is_cancelled(batch_id, batch.status):
                return

            if any(doc.status == DocumentStatus.FILLED_AUTO for doc in new_documents):
                auto_validate = True
    except asyncio.CancelledError:
        logger.info("Delta batch pipeline cancelled for %s", batch_id)
        raise
    finally:
        await task_tracker.remove_task(batch_id, kind="process_delta")

    if auto_validate:
        try:
            await base_pipeline.run_validation_pipeline(batch_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic validation failed for batch %s (delta)", batch_id)


async def enqueue_batch_processing_parallel(batch_id: uuid.UUID) -> str:
    return await base_pipeline._start_local_task(
        batch_id,
        kind="process",
        runner=run_batch_pipeline_parallel,
    )


async def enqueue_batch_delta_processing_parallel(batch_id: uuid.UUID) -> str:
    return await base_pipeline._start_local_task(
        batch_id,
        kind="process_delta",
        runner=run_batch_delta_pipeline_parallel,
    )
