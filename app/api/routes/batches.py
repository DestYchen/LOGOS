from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.api.schemas import (
    BatchSummary,
    BatchCreateRequest,
    BatchCreateResponse,
    BatchReportResponse,
    BatchUploadResponse,
    DocumentSummary,
    FieldUpdateRequest,
    ReviewCompleteResponse,
    ReviewField,
    ReviewResponse,
)
from app.core.config import get_settings
from app.core.enums import BatchStatus, DocumentStatus
from app.services import batches as batch_service
from app.services import deletion
from app.services import pipeline, reports, review

router = APIRouter(prefix="/batches", tags=["batches"])


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
        documents=documents,
    )


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
    batch = await batch_service.create_batch(session, payload.created_by if payload else None)
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
    return BatchUploadResponse(saved=saved)


@router.post("/{batch_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    task_id = await pipeline.enqueue_batch_processing(batch_id)
    return {"batch_id": batch_id, "task_id": task_id}


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
async def complete_review(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    settings = get_settings()
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    if not review.review_ready(batch, settings.low_conf_threshold):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="review_not_complete")

    for document in batch.documents:
        document.status = DocumentStatus.FILLED_REVIEWED
    batch.status = BatchStatus.FILLED_REVIEWED
    await session.flush()

    await pipeline.enqueue_validation(batch_id)
    return ReviewCompleteResponse(batch_id=batch.id, status=batch.status)


@router.get("/{batch_id}/report", response_model=BatchReportResponse)
async def get_report(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    try:
        payload = reports.load_report(batch_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report_not_ready") from None

    validations = payload.get("validations", [])
    meta = payload.get("meta", {})
    return BatchReportResponse(
        batch_id=batch.id,
        status=batch.status,
        validations=validations,
        meta=meta,
    )

@router.post("/{batch_id}/delete")
async def delete_batch_api(batch_id: uuid.UUID) -> dict:
    try:
        result = await deletion.delete_batch(batch_id, requested_by="api")
    except deletion.BatchNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found") from exc

    return {"batch_id": str(batch_id), "documents": result.get("documents", 0)}
