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
from app.services import deletion
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
    # Ensure DB rows are visible for the worker and subsequent GET before enqueue/redirect
    await session.flush()
    await session.commit()
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
            # Разрешаем удаление не только для DONE/FAILED, а для любых статусов,
            # так как удаление теперь безопасно обрабатывает отмену задач.
            "can_delete": item.status in (
                BatchStatus.NEW,
                BatchStatus.PREPARED,
                BatchStatus.TEXT_READY,
                BatchStatus.CLASSIFIED,
                BatchStatus.FILLED_AUTO,
                BatchStatus.FILLED_REVIEWED,
                BatchStatus.VALIDATED,
                BatchStatus.DONE,
                BatchStatus.FAILED,
                getattr(BatchStatus, "CANCEL_REQUESTED", BatchStatus.DONE),
                getattr(BatchStatus, "CANCELLED", BatchStatus.DONE),
            ),
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

        products_table = _build_product_table(document)

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
                "products": products_table,
            }
        )

    report_json = None
    report_documents: List[Dict[str, Any]] = []
    report_validations: List[Dict[str, Any]] = []
    report_available = False
    product_comparisons: List[Dict[str, Any]] = []
    report_payload: Optional[Dict[str, Any]] = None
    try:
        report_payload = await asyncio.to_thread(reports.load_report, batch_id)
        report_json = json.dumps(report_payload, indent=2, ensure_ascii=False)
        doc_rows, validation_rows = reports.build_report_tables(report_payload)
        report_documents = doc_rows
        report_validations = validation_rows
        report_available = True
        product_comparisons = _build_product_comparisons(report_payload)
    except FileNotFoundError:
        report_json = None
        report_payload = None

    product_matrix_columns, product_matrix = _build_product_comparison_matrix(product_comparisons)
    validation_matrix_columns, validation_matrix = _build_validation_matrix(report_payload, documents_payload)

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
        "product_comparisons": product_comparisons,
        "product_matrix_columns": product_matrix_columns,
        "product_matrix": product_matrix,
        "validation_matrix_columns": validation_matrix_columns,
        "validation_matrix": validation_matrix,
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
    # Commit statuses before enqueue to avoid concurrent updates on the same batch row
    await session.commit()

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


def _build_product_comparisons(report_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not report_payload:
        return []
    # Если отчёт содержит такой раздел — вернём его; иначе пусто.
    return list(report_payload.get("product_comparisons", []))

def _build_product_comparison_matrix(product_comparisons: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    # Минимально: пустая матрица, если логика ещё не реализована
    return [], []

def _format_doc_type_label(key: str) -> str:
    # Можно маппить на красивые лейблы, а пока — просто вернуть как есть
    return key


def _build_product_table(document: Document) -> Dict[str, Any]:
    schema = get_schema(document.doc_type)
    products_schema = schema.fields.get("products") if schema else None
    template = None
    if products_schema and products_schema.children:
        template = products_schema.children.get("product_template")

    # Если шаблона нет — пустая таблица
    if template is None or not template.children:
        return {"columns": [], "rows": []}

    # Колонки: ключ и человекочитаемый лейбл
    columns: List[Dict[str, str]] = []
    column_keys: List[str] = []
    for key, field_schema in template.children.items():
        columns.append({"key": key, "label": field_schema.label or key})
        column_keys.append(key)

    # Последние значения полей документа
    latest_fields: Dict[str, FilledField] = {
        f.field_key: f for f in document.fields if getattr(f, "latest", False)
    }

    # products_map: {product_id: {sub_key: FilledField}}
    products_map: Dict[str, Dict[str, FilledField]] = {}
    for field_key, field in latest_fields.items():
        if not field_key.startswith("products."):
            continue
        parts = field_key.split(".")
        if len(parts) < 3:
            continue
        product_id = parts[1]
        sub_key = ".".join(parts[2:])
        products_map.setdefault(product_id, {})[sub_key] = field

    # Строки таблицы
    rows: List[Dict[str, Any]] = []
    for product_id, subfields in sorted(products_map.items(), key=lambda kv: kv[0]):
        row_cells: Dict[str, Any] = {}
        for key in column_keys:
            # Берём именно значение для этой колонки (sub_key)
            fld = subfields.get(key)
            row_cells[key] = fld.value if fld is not None else None
        rows.append({
            "product_id": product_id,
            "cells": row_cells,
        })

    return {"columns": columns, "rows": rows}





def _format_validation_detail(
    ref: Dict[str, Any],
    doc_info: Optional[Dict[str, Any]],
) -> Optional[str]:
    label = doc_info.get('filename') or doc_info.get('doc_type') if doc_info else None
    value = ref.get('value')
    field_key = ref.get('field_key') or ref.get('field')
    parts: List[str] = []
    if value not in (None, '', []):
        parts.append(str(value))
    if field_key:
        parts.append(str(field_key))
    detail = ' • '.join(parts) if parts else None
    # if label:
    #     return f"{label}: {detail}" if detail else label
    return detail if detail else "---"



def _build_validation_matrix(
    report_payload: Optional[Dict[str, Any]],
    documents_payload: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    if not report_payload:
        return [], []

    validations = report_payload.get('validations') or []
    if not validations:
        return [], []

    doc_info: Dict[str, Dict[str, str]] = {}
    for doc in documents_payload:
        doc_id = str(doc.get('id')) if doc.get('id') is not None else None
        if doc_id:
            doc_info[doc_id] = {
                'doc_type': doc.get('doc_type'),
                'filename': doc.get('filename'),
            }

    for doc in report_payload.get('documents', []):
        doc_id = doc.get('doc_id')
        if doc_id is None:
            continue
        key = str(doc_id)
        info = doc_info.get(key, {}).copy()
        if doc.get('doc_type'):
            info['doc_type'] = doc.get('doc_type')
        if doc.get('filename'):
            info['filename'] = doc.get('filename')
        doc_info[key] = info

    doc_types_present: set[str] = set()
    for info in doc_info.values():
        doc_type = info.get('doc_type')
        if doc_type:
            doc_types_present.add(doc_type)

    for item in validations:
        for ref in item.get('refs', []):
            ref_doc_type = ref.get('doc_type')
            if ref_doc_type:
                doc_types_present.add(ref_doc_type)
            doc_id = ref.get('doc_id')
            if doc_id is not None:
                info = doc_info.get(str(doc_id))
                if info and info.get('doc_type'):
                    doc_types_present.add(info['doc_type'])

    columns: List[Dict[str, str]] = []
    used_keys: set[str] = set()
    for doc_type in DocumentType:
        key = doc_type.value
        if key in doc_types_present:
            columns.append({'key': key, 'label': _format_doc_type_label(key)})
            used_keys.add(key)
    for key in sorted(doc_types_present):
        if key not in used_keys:
            columns.append({'key': key, 'label': _format_doc_type_label(key)})
            used_keys.add(key)

    rows: List[Dict[str, Any]] = []
    for item in validations:
        cells_map: Dict[str, List[str]] = {col['key']: [] for col in columns}
        for ref in item.get('refs', []):
            doc_id = ref.get('doc_id')
            info = doc_info.get(str(doc_id)) if doc_id is not None else None
            doc_type = info.get('doc_type') if info and info.get('doc_type') else ref.get('doc_type')
            if not doc_type:
                continue
            if doc_type not in cells_map:
                cells_map[doc_type] = []
            detail = _format_validation_detail(ref, info)
            if detail:
                cells_map[doc_type].append(detail)

        rows.append(
            {
                'rule_id': item.get('rule_id'),
                'severity': item.get('severity'),
                'message': item.get('message'),
                'cells': {key: '\n'.join(values) if values else None for key, values in cells_map.items()},
            }
        )

    return columns, rows


def _latest_field(document: Document, field_key: str) -> Optional[FilledField]:
    for field in document.fields:
        if field.field_key == field_key and field.latest:
            return field
    return None


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@router.post("/batches/{batch_id}/delete")
async def delete_batch(batch_id: uuid.UUID) -> RedirectResponse:
    try:
        await deletion.delete_batch(batch_id, requested_by="web")
    except deletion.BatchNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found") from exc

    return RedirectResponse(
        url="/web/batches?message=batch_deleted",
        status_code=status.HTTP_303_SEE_OTHER,
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


@router.post("/documents/{doc_id}/refill")
async def refill_document(
    doc_id: uuid.UUID,
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

    if document.doc_type == DocumentType.UNKNOWN:
        return RedirectResponse(
            url=f"/web/batches/{document.batch_id}?error=type_required",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    await pipeline.fill_document_from_existing_ocr(
        session,
        batch_id=document.batch_id,
        document=document,
        forced_doc_type=document.doc_type,
    )
    await session.flush()
    return RedirectResponse(
        url=f"/web/batches/{document.batch_id}?message=refilled",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/documents/{doc_id}/delete")
async def delete_document(
    doc_id: uuid.UUID,
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

    # Remove files on disk (best-effort)
    from pathlib import Path as _Path
    import shutil as _shutil
    paths = batch_dir(str(document.batch_id))
    try:
        raw_file = paths.raw / document.filename
        raw_file.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass
    try:
        if document.ocr_path:
            (paths.base / document.ocr_path).unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass
    try:
        if document.filled_path:
            (paths.base / document.filled_path).unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass
    # Remove derived/preview folders for the document
    try:
        _shutil.rmtree(paths.derived / str(document.id), ignore_errors=True)
    except Exception:
        pass
    try:
        _shutil.rmtree(paths.preview / str(document.id), ignore_errors=True)
    except Exception:
        pass

    batch_id = document.batch_id
    await session.delete(document)
    await session.flush()

    return RedirectResponse(
        url=f"/web/batches/{batch_id}?message=document_deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )
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



