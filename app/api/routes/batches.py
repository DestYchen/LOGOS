from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.api.schemas import (
    BatchSummary,
    BatchCreateRequest,
    BatchCreateResponse,
    BatchReportResponse,
    BatchUploadResponse,
    ReportDocument,
    ReportFieldValue,
    DocumentSummary,
    FieldUpdateRequest,
    ReviewCompleteResponse,
    ReviewField,
    ReviewResponse,
    ValidationResult,
)
from app.core.config import get_settings
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.services import batches as batch_service
from app.services import deletion
from app.services import pipeline, reports, reporting, review, validation

router = APIRouter(prefix="/batches", tags=["batches"])
logger = logging.getLogger(__name__)


def _serialize_batch_summary(batch) -> BatchSummary:
    documents = [
        DocumentSummary(
            id=document.id,
            filename=document.filename,
            status=document.status,
            doc_type=document.doc_type,
            pages=getattr(document, "pages", 0) or 0,
        )
        for document in batch.documents
    ]
    return BatchSummary(
        id=batch.id,
        status=batch.status,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        created_by=batch.created_by,
        title=batch_service.extract_batch_title(batch),
        documents=documents,
    )


async def _generate_report_inline(session: AsyncSession, batch_id: uuid.UUID) -> Dict[str, Any]:
    messages = await validation.validate_batch(session, batch_id)
    await validation.store_validations(session, batch_id, messages)
    payload = await reporting.generate_report(session, batch_id)
    await session.commit()
    return payload


@router.get("/", response_model=List[BatchSummary])
async def list_batches_api(session: AsyncSession = Depends(get_db)) -> List[BatchSummary]:
    batches = await batch_service.list_batch_summaries(session)
    return [_serialize_batch_summary(batch) for batch in batches]


@router.get("/{batch_id}", response_model=BatchSummary)
async def batch_summary(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> BatchSummary:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    return _serialize_batch_summary(batch)

@router.post("/", response_model=BatchCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(
    payload: BatchCreateRequest | None = None,
    session: AsyncSession = Depends(get_db),
):
    created_by = payload.created_by if payload else None
    title = payload.title if payload else None
    batch = await batch_service.create_batch(session, created_by, title)
    return BatchCreateResponse(batch_id=batch.id)


@router.post("/{batch_id}/upload", response_model=BatchUploadResponse)
async def upload_documents(
    batch_id: uuid.UUID,
    files: List[UploadFile] = File(...),
    session: AsyncSession = Depends(get_db),
):
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files_required")

    saved = await batch_service.save_documents(session, batch, files)
    if not saved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload_failed")
    meta = dict(batch.meta) if isinstance(batch.meta, dict) else {}
    meta["prep_complete"] = False
    batch.meta = meta
    return BatchUploadResponse(saved=saved)


@router.post("/{batch_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    meta = dict(batch.meta) if isinstance(batch.meta, dict) else {}
    prep_complete = meta.get("prep_complete")
    if prep_complete is False or (prep_complete is None and batch.status in (BatchStatus.NEW, BatchStatus.PREPARED)):
        if not batch.documents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_empty")
        # Backwards compatibility: explicit process call confirms prep.
        meta["prep_complete"] = True
        if batch.status in (BatchStatus.NEW, BatchStatus.PREPARED):
            run_meta = meta.get("processing_run")
            if not isinstance(run_meta, dict) or run_meta.get("mode") != "initial_upload":
                meta["processing_run"] = {
                    "mode": "initial_upload",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "doc_ids": [str(doc.id) for doc in batch.documents],
                }
        batch.meta = meta
        await session.flush()
        await session.commit()
    task_id = await pipeline.enqueue_batch_processing(batch_id)
    return {"batch_id": batch_id, "task_id": task_id}


@router.post("/{batch_id}/confirm-prep", status_code=status.HTTP_202_ACCEPTED)
async def confirm_prep(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    if not batch.documents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_empty")

    meta = dict(batch.meta) if isinstance(batch.meta, dict) else {}
    if meta.get("prep_complete"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="prep_locked")

    meta["prep_complete"] = True
    if batch.status in (BatchStatus.NEW, BatchStatus.PREPARED):
        run_meta = meta.get("processing_run")
        if not isinstance(run_meta, dict) or run_meta.get("mode") != "initial_upload":
            meta["processing_run"] = {
                "mode": "initial_upload",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "doc_ids": [str(doc.id) for doc in batch.documents],
            }
    batch.meta = meta
    await session.flush()
    await session.commit()

    if batch.status in (BatchStatus.NEW, BatchStatus.PREPARED):
        task_id = await pipeline.enqueue_batch_processing(batch.id)
        kind = "process"
    else:
        task_id = await pipeline.enqueue_batch_delta_processing(batch.id)
        kind = "process_delta"

    return {
        "status": "ok",
        "message": "prep_confirmed",
        "batch_id": str(batch.id),
        "task_id": task_id,
        "kind": kind,
    }


@router.get("/{batch_id}/review", response_model=ReviewResponse)
async def get_review(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    settings = get_settings()
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    fields_data = review.collect_review_data(batch, settings.low_conf_threshold)
    fields = [
        ReviewField(
            doc_id=item.doc_id,
            document_filename=item.document_filename,
            field_key=item.field_key,
            value=item.value,
            confidence=item.confidence,
            required=item.required,
            threshold=settings.low_conf_threshold,
            source=item.source,
            page=item.page,
            bbox=item.bbox,
            token_refs=item.token_refs,
            doc_type=item.doc_type,
        )
        for item in fields_data
    ]
    return ReviewResponse(
        batch_id=batch.id,
        status=batch.status,
        low_conf_threshold=settings.low_conf_threshold,
        fields=fields,
    )


@router.post("/documents/{doc_id}/fields/{field_key}")
async def update_field(
    doc_id: uuid.UUID,
    field_key: str,
    payload: FieldUpdateRequest,
    session: AsyncSession = Depends(get_db),
):
    try:
        field = await review.upsert_field(
            session=session,
            doc_id=doc_id,
            field_key=field_key,
            value=payload.value,
            bbox=payload.bbox,
            token_refs=payload.token_refs,
            edited_by="user",
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found") from None

    return {
        "doc_id": doc_id,
        "field_key": field_key,
        "version": field.version,
        "confidence": field.confidence,
    }


@router.post("/{batch_id}/review/complete", response_model=ReviewCompleteResponse)
async def complete_review(batch_id: uuid.UUID, force: bool = False, session: AsyncSession = Depends(get_db)):
    settings = get_settings()
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    ready = review.review_ready(batch, settings.low_conf_threshold)
    issues: List[str] = []
    try:
        from app.core.schema import get_schema  # local import to avoid circular dependency at module import time
        from app.models import FilledField

        for document in batch.documents:
            latest_fields: Dict[str, FilledField] = {
                field.field_key: field for field in document.fields if field.latest
            }
            schema = get_schema(document.doc_type)
            if document.doc_type == DocumentType.UNKNOWN:
                issues.append(f"{document.filename}: doc_type UNKNOWN")
            for key, field_schema in schema.fields.items():
                field = latest_fields.get(key)
                if field_schema.required and (field is None or field.value is None):
                    issues.append(f"{document.filename}: missing required {key}")
                elif field is not None and field.confidence < settings.low_conf_threshold:
                    issues.append(
                        f"{document.filename}: low confidence {key}={field.confidence:.3f} (<{settings.low_conf_threshold})"
                    )
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.debug("Failed to collect review diagnostics for batch %s: %s", batch_id, exc, exc_info=True)

    logger.info(
        "Review completion requested batch=%s ready=%s force=%s issues=%s",
        batch_id,
        ready,
        force,
        issues[:10],
    )
    warnings: List[str] = []
    if not ready:
        if not force:
            logger.warning("Rejecting completion for batch %s: review not ready (%s)", batch_id, issues[:10])
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="review_not_complete")
        warnings.append("review_not_complete")

    for document in batch.documents:
        document.status = DocumentStatus.FILLED_REVIEWED
    batch.status = BatchStatus.FILLED_REVIEWED
    await session.flush()

    if warnings:
        meta = dict(batch.meta or {})
        existing = list(meta.get("processing_warnings", [])) if isinstance(meta.get("processing_warnings"), list) else []
        for item in warnings:
            if item not in existing:
                existing.append(item)
        meta["processing_warnings"] = existing
        batch.meta = meta

    task_id = await pipeline.enqueue_validation(batch_id)
    logger.info("Validation enqueued for batch %s (task_id=%s, warnings=%s)", batch_id, task_id, warnings)
    return ReviewCompleteResponse(batch_id=batch.id, status=batch.status, warnings=warnings)


@router.get("/{batch_id}/report", response_model=BatchReportResponse)
async def get_report(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    try:
        payload = reports.load_report(batch_id)
    except FileNotFoundError:
        payload = await _generate_report_inline(session, batch_id)
    validations_payload = payload.get("validations", [])
    meta = payload.get("meta", {})
    documents_payload = payload.get("documents", [])
    generated_at = payload.get("generated_at")
    status_value = payload.get("status")
    response_status = batch.status
    if status_value:
        try:
            response_status = BatchStatus(status_value)
        except ValueError:
            response_status = batch.status

    documents: List[ReportDocument] = []
    for item in documents_payload:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("doc_id")
        if doc_id is None:
            continue
        filename = item.get("filename", "")
        doc_type_value = item.get("doc_type")
        doc_status_value = item.get("status")
        fields_payload = item.get("fields") or {}
        fields: Dict[str, ReportFieldValue] = {}
        if isinstance(fields_payload, dict):
            for key, value in fields_payload.items():
                if not isinstance(key, str):
                    continue
                if isinstance(value, dict):
                    fields[key] = ReportFieldValue(**value)
                else:
                    fields[key] = ReportFieldValue(value=value)
        try:
            doc_type_enum = DocumentType(doc_type_value) if doc_type_value else DocumentType.UNKNOWN
        except ValueError:
            doc_type_enum = DocumentType.UNKNOWN
        try:
            doc_status_enum = DocumentStatus(doc_status_value) if doc_status_value else DocumentStatus.FILLED_AUTO
        except ValueError:
            doc_status_enum = DocumentStatus.FILLED_AUTO
        try:
            documents.append(
                ReportDocument(
                    doc_id=doc_id,
                    filename=filename,
                    doc_type=doc_type_enum,
                    status=doc_status_enum,
                    fields=fields,
                )
            )
        except Exception:
            continue

    validation_models = [
        ValidationResult(
            rule_id=item.get("rule_id", ""),
            severity=item.get("severity", ""),
            message=item.get("message", ""),
            refs=item.get("refs") or [],
        )
        for item in validations_payload
        if isinstance(item, dict)
    ]

    return BatchReportResponse(
        batch_id=batch.id,
        status=response_status,
        validations=validation_models,
        meta=meta,
        documents=documents,
        generated_at=generated_at,
    )

@router.post("/{batch_id}/delete")
async def delete_batch_api(batch_id: uuid.UUID) -> dict:
    try:
        result = await deletion.delete_batch(batch_id, requested_by="api")
    except deletion.BatchNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found") from exc

    return {"batch_id": str(batch_id), "documents": result.get("documents", 0)}
