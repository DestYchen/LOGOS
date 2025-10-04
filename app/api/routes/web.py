from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_db
from app.core.config import get_settings
from app.core.enums import BatchStatus, DocumentStatus, DocumentType
from app.core.schema import get_schema
from app.core.storage import batch_dir
from app.models import Document, FilledField
from app.services import batches as batch_service
from app.services import pipeline, reports, review

router = APIRouter(prefix="/web", tags=["web"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


@router.get("/upload", response_class=HTMLResponse)
async def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("upload.html", {"request": request})


@router.post("/upload")
async def handle_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    session: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files_required")

    batch = await batch_service.create_batch(session, created_by="web")
    await batch_service.save_documents(session, batch, files)
    await pipeline.enqueue_batch_processing(batch.id)
    return RedirectResponse(url=f"/web/batches/{batch.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/batches", response_class=HTMLResponse)
async def list_batches(request: Request, session: AsyncSession = Depends(get_db)) -> HTMLResponse:
    batches = await batch_service.list_batch_summaries(session)
    items = [
        {
            "id": str(item.id),
            "status": item.status.value,
            "documents_count": len(item.documents),
            "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
            "can_delete": item.status in (BatchStatus.DONE, BatchStatus.FAILED),
        }
        for item in batches
    ]
    message = request.query_params.get("message")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "batches.html",
        {"request": request, "batches": items, "message": message, "error": error},
    )


@router.get("/batches/{batch_id}", response_class=HTMLResponse)
async def batch_details(
    batch_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    batch_paths = batch_dir(str(batch_id))

    documents_payload: List[Dict[str, object]] = []
    pending_total = 0
    awaiting_processing = False

    for document in batch.documents:
        filled_json = None
        if document.filled_path:
            filled_file = batch_paths.base / document.filled_path
            if filled_file.exists():
                filled_data = await asyncio.to_thread(_read_json, filled_file)
                filled_json = json.dumps(filled_data, indent=2, ensure_ascii=False)
        else:
            awaiting_processing = True

        fields, pending_count = _build_field_states(document)
        pending_total += pending_count
        if filled_json is None:
            awaiting_processing = True

        documents_payload.append(
            {
                "id": str(document.id),
                "filename": document.filename,
                "status": document.status.value,
                "doc_type": document.doc_type.value,
                "filled_json": filled_json,
                "fields": fields,
                "pending_count": pending_count,
                "processing": filled_json is None,
            }
        )

    report_json = None
    report_documents: List[Dict[str, Any]] = []
    report_validations: List[Dict[str, Any]] = []
    report_available = False
    try:
        report_payload = await asyncio.to_thread(reports.load_report, batch_id)
        report_json = json.dumps(report_payload, indent=2, ensure_ascii=False)
        doc_rows, validation_rows = reports.build_report_tables(report_payload)
        report_documents = doc_rows
        report_validations = validation_rows
        report_available = True
    except FileNotFoundError:
        report_json = None


    can_complete = pending_total == 0 and not awaiting_processing

    message = request.query_params.get("message")
    error = request.query_params.get("error")

    context = {
        "request": request,
        "batch_id": str(batch.id),
        "status": batch.status.value,
        "documents": documents_payload,
        "report_json": report_json,
        "report_documents": report_documents,
        "report_validations": report_validations,
        "report_available": report_available,
        "message": message,
        "error": error,
        "doc_types": [dt.value for dt in DocumentType],
        "can_complete": can_complete,
        "pending_total": pending_total,
        "awaiting_processing": awaiting_processing,
    }
    return templates.TemplateResponse("batch.html", context)


@router.post("/batches/{batch_id}/complete")
async def complete_batch(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")

    pending_total = 0
    awaiting_processing = False
    for document in batch.documents:
        if document.filled_path is None:
            awaiting_processing = True
        _, pending_count = _build_field_states(document)
        pending_total += pending_count

    if awaiting_processing or pending_total > 0:
        return RedirectResponse(
            url=f"/web/batches/{batch_id}?error=review_not_ready",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    for document in batch.documents:
        document.status = DocumentStatus.FILLED_REVIEWED
    batch.status = BatchStatus.FILLED_REVIEWED
    await session.flush()

    await pipeline.enqueue_validation(batch_id)
    return RedirectResponse(
        url=f"/web/batches/{batch_id}?message=review_completed",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/documents/{doc_id}/fields/{field_key}/update")
async def update_field(
    doc_id: uuid.UUID,
    field_key: str,
    value: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    document = await _load_document(session, doc_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    latest = _latest_field(document, field_key)
    clean_value = value.strip() if value is not None else None
    new_value = clean_value if clean_value else None

    bbox = latest.bbox if latest else None
    token_refs = latest.token_refs if latest else None

    await review.upsert_field(
        session=session,
        doc_id=document.id,
        field_key=field_key,
        value=new_value,
        bbox=bbox,
        token_refs=token_refs,
        edited_by="web",
    )
    await session.flush()
    return RedirectResponse(
        url=f"/web/batches/{document.batch_id}?message=field_saved",
        status_code=status.HTTP_303_SEE_OTHER,
    )
@router.post("/documents/{doc_id}/fields/{field_key}/confirm")
async def confirm_field(
    doc_id: uuid.UUID,
    field_key: str,
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    document = await _load_document(session, doc_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    latest = _latest_field(document, field_key)
    if latest is None or latest.value in (None, ""):
        return RedirectResponse(
            url=f"/web/batches/{document.batch_id}?error=field_missing",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    await review.upsert_field(
        session=session,
        doc_id=document.id,
        field_key=field_key,
        value=latest.value,
        bbox=latest.bbox,
        token_refs=latest.token_refs,
        edited_by="web",
    )
    await session.flush()
    return RedirectResponse(
        url=f"/web/batches/{document.batch_id}?message=field_confirmed",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _load_document(session: AsyncSession, doc_id: uuid.UUID) -> Optional[Document]:
    stmt = (
        select(Document)
        .where(Document.id == doc_id)
        .options(selectinload(Document.fields), selectinload(Document.batch))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _build_field_states(document: Document) -> Tuple[List[Dict[str, object]], int]:
    fields: List[Dict[str, object]] = []
    pending = 0

    def add_field(
        *,
        field_key: str,
        value: Optional[str],
        confidence: Optional[float],
        required: bool,
        reason: str,
        actionable: bool,
        editable: bool,
    ) -> None:
        nonlocal pending
        needs_confirmation = reason in {"missing", "low_confidence"}
        if needs_confirmation:
            pending += 1
        fields.append(
            {
                "doc_id": str(document.id),
                "field_key": field_key,
                "value": value,
                "confidence": confidence,
                "confidence_display": f"{confidence:.2f}" if confidence is not None else None,
                "required": required,
                "reason": reason,
                "needs_confirmation": needs_confirmation,
                "actionable": actionable,
                "editable": editable,
            }
        )

    latest_fields: Dict[str, FilledField] = {
        field.field_key: field for field in document.fields if field.latest
    }

    if document.doc_type == DocumentType.UNKNOWN:
        add_field(
            field_key="doc_type",
            value=None,
            confidence=None,
            required=True,
            reason="unknown_type",
            actionable=False,
            editable=False,
        )
        for key, field in latest_fields.items():
            value = field.value
            confidence = float(field.confidence) if field.confidence is not None else None
            if value in (None, ""):
                add_field(
                    field_key=key,
                    value=value,
                    confidence=confidence,
                    required=False,
                    reason="missing",
                    actionable=False,
                    editable=True,
                )
            elif confidence is not None and confidence < settings.low_conf_threshold:
                add_field(
                    field_key=key,
                    value=value,
                    confidence=confidence,
                    required=False,
                    reason="low_confidence",
                    actionable=True,
                    editable=True,
                )
            else:
                add_field(
                    field_key=key,
                    value=value,
                    confidence=confidence,
                    required=False,
                    reason="ok",
                    actionable=False,
                    editable=False,
                )
        return fields, pending

    schema = get_schema(document.doc_type)

    processed_keys: set[str] = set()
    for key, field_schema in schema.fields.items():
        field = latest_fields.get(key)
        value = field.value if field else None
        confidence = float(field.confidence) if field and field.confidence is not None else None

        if value in (None, ""):
            add_field(
                field_key=key,
                value=value,
                confidence=confidence,
                required=field_schema.required,
                reason="missing",
                actionable=False,
                editable=True,
            )
        elif confidence is not None and confidence < settings.low_conf_threshold:
            add_field(
                field_key=key,
                value=value,
                confidence=confidence,
                required=field_schema.required,
                reason="low_confidence",
                actionable=True,
                editable=True,
            )
        else:
            add_field(
                field_key=key,
                value=value,
                confidence=confidence,
                required=field_schema.required,
                reason="ok",
                actionable=False,
                editable=False,
            )
        processed_keys.add(key)

    for key, field in latest_fields.items():
        if key in processed_keys:
            continue
        confidence = float(field.confidence) if field.confidence is not None else None
        add_field(
            field_key=key,
            value=field.value,
            confidence=confidence,
            required=False,
            reason="extra",
            actionable=False,
            editable=False,
        )

    return fields, pending
def _latest_field(document: Document, field_key: str) -> Optional[FilledField]:
    for field in document.fields:
        if field.field_key == field_key and field.latest:
            return field
    return None


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@router.post("/batches/{batch_id}/delete")
async def delete_batch(
    batch_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    batch = await batch_service.get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")
    if batch.status not in (BatchStatus.DONE, BatchStatus.FAILED):
        return RedirectResponse(
            url=f"/web/batches?error=delete_forbidden", status_code=status.HTTP_303_SEE_OTHER
        )

    # Remove DB entity (cascade deletes documents/fields/validations)
    await session.delete(batch)
    await session.flush()

    # Remove files from storage
    from app.core.storage import remove_batch as _remove_batch

    _remove_batch(str(batch_id))

    return RedirectResponse(
        url=f"/web/batches?message=batch_deleted", status_code=status.HTTP_303_SEE_OTHER
    )



@router.post("/documents/{doc_id}/set_type")
async def set_document_type(
    doc_id: uuid.UUID,
    doc_type: str = Form(...),
    session: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Document)
        .where(Document.id == doc_id)
        .options(selectinload(Document.batch), selectinload(Document.fields))
    )
    result = await session.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    from app.core.enums import DocumentType as _DT
    try:
        forced_type = _DT(doc_type)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_doc_type") from None
    await pipeline.fill_document_from_existing_ocr(session, batch_id=document.batch_id, document=document, forced_doc_type=forced_type)
    await session.flush()
    return RedirectResponse(url=f"/web/batches/{document.batch_id}?message=type_set", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/batches/{batch_id}/report.xlsx")
async def download_batch_report(batch_id: uuid.UUID) -> StreamingResponse:
    try:
        buffer = await asyncio.to_thread(reports.export_report_excel_for_batch, batch_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report_not_found")
    headers = {"Content-Disposition": f"attachment; filename=\"batch-{batch_id}-report.xlsx\""}
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )



