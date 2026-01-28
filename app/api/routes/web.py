from __future__ import annotations



import asyncio
import time
from datetime import datetime, timezone

import json

import uuid

from pathlib import Path

from typing import Any, Dict, List, Optional, Tuple



from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status

from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response

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

from app.services import feedback as feedback_service
from app.services import pipeline, reports, review
import fitz  # type: ignore import-not-found



router = APIRouter(prefix="/web", tags=["web"])

settings = get_settings()

_INTERNAL_DOC_TYPES = {
    DocumentType.CONTRACT_1,
    DocumentType.CONTRACT_2,
    DocumentType.CONTRACT_3,
}




FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "test frontend"

FRONTEND_DIST = FRONTEND_ROOT / "dist"

INDEX_HTML = FRONTEND_DIST / "index.html"





def _ensure_frontend_build() -> None:

    if not INDEX_HTML.exists():

        raise HTTPException(

            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,

            detail="frontend_not_built",

        )


def _feedback_error_message(code: str) -> str:
    mapping = {
        "subject_required": "Укажите тему.",
        "subject_too_long": "Тема слишком длинная.",
        "message_required": "Опишите проблему.",
        "message_too_long": "Описание слишком длинное.",
        "feedback_type_invalid": "Выберите тип обращения.",
        "contact_too_long": "Контакт слишком длинный.",
        "too_many_files": "Можно добавить не более 5 изображений.",
        "unsupported_file_type": "Поддерживаются только изображения JPG или PNG.",
        "file_too_large": "Размер каждого изображения не должен превышать 5 МБ.",
    }
    return mapping.get(code, "Не удалось отправить обратную связь.")





@router.get("/app", response_class=HTMLResponse)

async def serve_frontend_app() -> HTMLResponse:

    _ensure_frontend_build()

    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))





@router.get("/app/{path:path}")

async def serve_frontend_assets(path: str) -> Response:

    _ensure_frontend_build()

    if path in ("", "index.html"):

        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))



    target = (FRONTEND_DIST / path).resolve()

    dist_root = FRONTEND_DIST.resolve()

    if not str(target).startswith(str(dist_root)):

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")



    if not target.exists():

        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))



    if target.is_dir():

        index_candidate = target / "index.html"

        if index_candidate.exists():

            return HTMLResponse(index_candidate.read_text(encoding="utf-8"))

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")



    if target.suffix.lower() in {".html"}:

        return HTMLResponse(target.read_text(encoding="utf-8"))

    return FileResponse(target)





@router.post("/upload")

async def handle_upload(

    files: List[UploadFile] = File(...),

    title: Optional[str] = Form(None),

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    if not files:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files_required")



    batch = await batch_service.create_batch(session, created_by="web", title=title)

    saved_urls = await batch_service.save_documents(session, batch, files)

    await session.flush()

    await session.commit()



    return {

        "status": "ok",

        "batch_id": str(batch.id),

        "documents": len(saved_urls),

        "document_urls": saved_urls,

    }




@router.post("/api/batches/{batch_id}/upload")

async def upload_batch_documents(

    batch_id: uuid.UUID,

    files: List[UploadFile] = File(...),

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    batch = await batch_service.get_batch(session, batch_id)

    if batch is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")



    if batch.status in (BatchStatus.CANCEL_REQUESTED, BatchStatus.CANCELLED):

        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_cancelled")



    if not files:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files_required")



    saved_urls = await batch_service.save_documents(session, batch, files, update_status=False)

    if not saved_urls:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="upload_failed")

    meta = dict(batch.meta) if isinstance(batch.meta, dict) else {}
    meta["prep_complete"] = False
    batch.meta = meta



    await session.flush()

    await session.commit()


    return {

        "status": "ok",

        "batch_id": str(batch.id),

        "documents": len(saved_urls),

        "document_urls": saved_urls,

    }






@router.post("/api/batches/{batch_id}/confirm-prep")

async def confirm_batch_prep(

    batch_id: uuid.UUID,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    batch = await batch_service.get_batch(session, batch_id)

    if batch is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")



    if _prep_complete(batch):

        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="prep_locked")



    if not batch.documents:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_empty")



    meta = dict(batch.meta) if isinstance(batch.meta, dict) else {}

    meta["prep_complete"] = True

    if batch.status in (BatchStatus.NEW, BatchStatus.PREPARED):
        run_meta = meta.get("processing_run")
        if not isinstance(run_meta, dict) or run_meta.get("mode") != "initial_upload":
            doc_ids = [
                str(document.id)
                for document in batch.documents
                if document.doc_type not in _INTERNAL_DOC_TYPES
            ]
            meta["processing_run"] = {
                "mode": "initial_upload",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "doc_ids": doc_ids,
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




@router.get("/api/doc_types")

async def list_doc_types() -> Dict[str, Any]:

    return {"doc_types": [doc_type.value for doc_type in DocumentType if doc_type not in _INTERNAL_DOC_TYPES]}





@router.get("/api/batches")

async def list_batches(session: AsyncSession = Depends(get_db)) -> Dict[str, Any]:

    batches = await batch_service.list_batch_summaries(session)

    items = [

        {

            "id": str(item.id),

            "status": item.status.value,

            "documents_count": len(item.documents),

            "created_at": item.created_at.isoformat() if item.created_at else None,

            "created_at_display": item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else None,

            "title": batch_service.extract_batch_title(item),

            "can_delete": item.status

            in (

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

    return {"batches": items}





@router.get("/api/batches/{batch_id}")

async def get_batch_details(

    batch_id: uuid.UUID,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    batch = await batch_service.get_batch(session, batch_id)

    if batch is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found")



    batch_paths = batch_dir(str(batch_id))



    documents_payload: List[Dict[str, Any]] = []

    pending_total = 0

    awaiting_processing = False



    for document in batch.documents:
        if document.doc_type in _INTERNAL_DOC_TYPES:
            continue

        filled_json: Optional[str] = None

        if document.filled_path:

            filled_file = batch_paths.base / document.filled_path

            if filled_file.exists():

                filled_data = await asyncio.to_thread(_read_json, filled_file)

                filled_json = json.dumps(filled_data, indent=2, ensure_ascii=False)

        else:
            if document.status != DocumentStatus.FAILED:
                awaiting_processing = True



        previews: List[str] = []

        try:

            preview_dir = batch_paths.preview / str(document.id)

            if preview_dir.exists():

                files = sorted(

                    (p for p in preview_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"),

                    key=lambda p: (len(p.name), p.name),

                )

                previews = [

                    f"/files/batches/{batch_id}/preview/{document.id}/{preview.name}"

                    for preview in files

                ]

        except Exception:

            previews = []



        fields, pending_count = _build_field_states(document)

        pending_total += pending_count

        if filled_json is None and document.status != DocumentStatus.FAILED:
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

                "previews": previews,
                "mime": document.mime,
                "updated_at": document.updated_at.isoformat() if document.updated_at else None,

            }

        )



    report_payload: Optional[Dict[str, Any]] = None

    report_json: Optional[str] = None

    report_field_matrix: Optional[Dict[str, Any]] = None
    report_field_matrix_diff: Optional[Dict[str, Any]] = None
    report_documents: List[Dict[str, Any]] = []

    report_validations: List[Dict[str, Any]] = []

    report_available = False

    product_comparisons: List[Dict[str, Any]] = []



    try:

        report_payload = await asyncio.to_thread(reports.load_report, batch_id)

        report_json = json.dumps(report_payload, indent=2, ensure_ascii=False)

        report_field_matrix, report_documents, report_validations = reports.build_report_tables(report_payload)
        report_field_matrix_diff = reports.extract_document_matrix_diff(report_payload)

        report_available = True

        product_comparisons = _build_product_comparisons(report_payload)

    except FileNotFoundError:

        report_payload = None



    product_matrix_columns, product_matrix = _build_product_comparison_matrix(product_comparisons)

    validation_matrix_columns, validation_matrix = _build_validation_matrix(report_payload, documents_payload)



    processed_meta = batch.meta or {}

    warnings_raw = processed_meta.get("processing_warnings") if isinstance(processed_meta, dict) else []

    processing_warnings = [str(item) for item in warnings_raw] if isinstance(warnings_raw, list) else []

    processing_run: Optional[Dict[str, Any]] = None
    run_meta = processed_meta.get("processing_run") if isinstance(processed_meta, dict) else None
    if isinstance(run_meta, dict) and run_meta.get("mode") == "initial_upload":
        doc_ids_raw = run_meta.get("doc_ids")
        doc_id_set = set()
        if isinstance(doc_ids_raw, list):
            doc_id_set = {str(item) for item in doc_ids_raw if item}
        current_doc_ids = {
            str(document.id)
            for document in batch.documents
            if document.doc_type not in _INTERNAL_DOC_TYPES
        }
        if not doc_id_set:
            doc_id_set = current_doc_ids
        else:
            doc_id_set = doc_id_set & current_doc_ids
        total = len(doc_id_set)
        completed = 0
        failed = 0
        steps_total = total * 2
        steps_completed = 0
        steps_failed = 0
        if total:
            for document in batch.documents:
                if document.doc_type in _INTERNAL_DOC_TYPES:
                    continue
                if str(document.id) not in doc_id_set:
                    continue
                ocr_failed = (
                    document.status == DocumentStatus.FAILED
                    and (not document.ocr_path or document.doc_type == DocumentType.UNKNOWN)
                )
                if document.status in (DocumentStatus.FILLED_AUTO, DocumentStatus.FILLED_REVIEWED, DocumentStatus.FAILED):
                    completed += 1
                    if document.status == DocumentStatus.FAILED:
                        failed += 1
                if ocr_failed:
                    steps_completed += 2
                    steps_failed += 2
                    continue
                ocr_done = bool(document.ocr_path) or document.status in (
                    DocumentStatus.TEXT_READY,
                    DocumentStatus.FILLED_AUTO,
                    DocumentStatus.FILLED_REVIEWED,
                )
                if ocr_done:
                    steps_completed += 1
                filler_done = bool(document.filled_path) or document.status in (
                    DocumentStatus.FILLED_AUTO,
                    DocumentStatus.FILLED_REVIEWED,
                )
                if filler_done:
                    steps_completed += 1
                elif document.status == DocumentStatus.FAILED:
                    steps_failed += 1
        if steps_total:
            steps_completed = min(steps_completed, steps_total)
            steps_failed = min(steps_failed, steps_total)
        processing_run = {
            "mode": "initial_upload",
            "started_at": run_meta.get("started_at"),
            "doc_ids": list(doc_id_set),
            "total": total,
            "completed": completed,
            "failed": failed,
            "steps_total": steps_total,
            "steps_completed": steps_completed,
            "steps_failed": steps_failed,
        }

    prep_complete = _prep_complete(batch)

    can_complete = pending_total == 0 and not awaiting_processing



    return {

        "batch": {

            "id": str(batch.id),

            "status": batch.status.value,

            "title": batch_service.extract_batch_title(batch),

            "created_at": batch.created_at.isoformat() if batch.created_at else None,

            "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,

            "documents": documents_payload,

            "documents_count": len(documents_payload),

            "doc_types": [doc_type.value for doc_type in DocumentType if doc_type not in _INTERNAL_DOC_TYPES],

            "pending_total": pending_total,

            "awaiting_processing": awaiting_processing,

            "can_complete": can_complete,

            "processing_warnings": processing_warnings,

            "prep_complete": prep_complete,
            "processing_run": processing_run,

            "report": {

                "available": report_available,

                "field_matrix": report_field_matrix,
                "field_matrix_diff": report_field_matrix_diff,

                "documents": report_documents,

                "validations": report_validations,

                "product_comparisons": product_comparisons,

                "product_matrix_columns": product_matrix_columns,

                "product_matrix": product_matrix,

                "validation_matrix_columns": validation_matrix_columns,

                "validation_matrix": validation_matrix,

                "raw_json": report_json,

            },

            "links": {

                "report_xlsx": f"/web/batches/{batch_id}/report.xlsx" if report_available else None,

            },

        }

    }





@router.post("/api/feedback")

async def submit_feedback(

    request: Request,

    subject: str = Form(...),

    message: str = Form(...),

    feedback_type: str = Form("problem"),

    contact: Optional[str] = Form(None),

    context: Optional[str] = Form(None),

    files: List[UploadFile] = File(default=[]),

) -> Dict[str, Any]:

    meta = {

        "user_agent": request.headers.get("user-agent"),

        "remote_ip": request.client.host if request.client else None,

    }

    try:

        ticket_id, ticket_dir, payload, saved_files = await feedback_service.store_feedback(

            subject,

            message,

            feedback_type,

            contact,

            context,

            files or [],

            meta=meta,

        )

    except feedback_service.FeedbackValidationError as exc:

        detail = _feedback_error_message(str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc



    sent = await feedback_service.send_to_telegram(payload, saved_files)

    if sent:

        feedback_service.cleanup_feedback(ticket_dir)



    return {

        "status": "sent" if sent else "stored",

        "ticket_id": ticket_id,

    }



@router.post("/api/batches/{batch_id}/complete")

async def complete_batch(

    batch_id: uuid.UUID,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

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

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="review_not_ready")



    for document in batch.documents:

        document.status = DocumentStatus.FILLED_REVIEWED

    batch.status = BatchStatus.FILLED_REVIEWED

    await session.flush()

    await session.commit()



    await pipeline.enqueue_validation(batch_id)

    return {"status": "ok", "message": "review_completed"}





@router.post("/api/documents/{doc_id}/fields/{field_key}/update")

async def update_field(

    doc_id: uuid.UUID,

    field_key: str,

    payload: Dict[str, Optional[str]] = Body(...),

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")



    batch_id = document.batch_id

    new_value = payload.get("value")

    if isinstance(new_value, str):

        clean_value = new_value.strip()

        normalized_value: Optional[str] = clean_value if clean_value else None

    elif new_value is None:

        normalized_value = None

    else:

        normalized_value = str(new_value).strip() or None



    latest = _latest_field(document, field_key)

    bbox = latest.bbox if latest else None

    token_refs = latest.token_refs if latest else None



    await review.upsert_field(

        session=session,

        doc_id=document.id,

        field_key=field_key,

        value=normalized_value,

        bbox=bbox,

        token_refs=token_refs,

        edited_by="web",

    )

    await session.flush()

    await session.commit()

    await pipeline.run_validation_pipeline(batch_id)

    return {

        "status": "ok",

        "message": "field_saved",

        "doc_id": str(document.id),

        "field_key": field_key,

        "value": normalized_value,

    }





@router.post("/api/documents/{doc_id}/fields/{field_key}/confirm")

async def confirm_field(

    doc_id: uuid.UUID,

    field_key: str,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")



    latest = _latest_field(document, field_key)

    if latest is None or latest.value in (None, ""):

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="field_missing")



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

    return {

        "status": "ok",

        "message": "field_confirmed",

        "doc_id": str(document.id),

        "field_key": field_key,

    }





@router.post("/api/batches/{batch_id}/delete")

async def delete_batch(batch_id: uuid.UUID) -> Dict[str, Any]:

    try:

        await deletion.delete_batch(batch_id, requested_by="web")

    except deletion.BatchNotFoundError as exc:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch_not_found") from exc



    return {"status": "ok", "message": "batch_deleted"}





@router.post("/api/documents/{doc_id}/set_type")

async def set_document_type(

    doc_id: uuid.UUID,

    payload: Dict[str, str] = Body(...),

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")



    doc_type_value = payload.get("doc_type")

    if not doc_type_value:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="doc_type_required")

    try:

        forced_type = DocumentType(doc_type_value)

    except ValueError as exc:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_doc_type") from exc



    await pipeline.fill_document_from_existing_ocr(

        session,

        batch_id=document.batch_id,

        document=document,

        forced_doc_type=forced_type,

    )

    await session.flush()
    await session.commit()
    await pipeline.run_validation_pipeline(document.batch_id)

    return {

        "status": "ok",

        "message": "type_set",

        "doc_id": str(document.id),

        "doc_type": forced_type.value,

        "batch_id": str(document.batch_id),

    }





@router.post("/api/documents/{doc_id}/refill")

async def refill_document(

    doc_id: uuid.UUID,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")



    if document.doc_type == DocumentType.UNKNOWN:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="type_required")



    await pipeline.fill_document_from_existing_ocr(

        session,

        batch_id=document.batch_id,

        document=document,

        forced_doc_type=document.doc_type,

    )

    await session.flush()
    await session.commit()
    await pipeline.run_validation_pipeline(document.batch_id)

    return {

        "status": "ok",

        "message": "refilled",

        "doc_id": str(document.id),

        "batch_id": str(document.batch_id),

    }






@router.post("/api/documents/{doc_id}/rotate")

async def rotate_document(

    doc_id: uuid.UUID,

    payload: Dict[str, Any] = Body(...),

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")



    _ensure_prep_open(document.batch)



    degrees_raw = payload.get("degrees")

    if degrees_raw is None:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="degrees_required")

    try:

        degrees = int(degrees_raw)

    except (TypeError, ValueError) as exc:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="degrees_invalid") from exc

    if degrees not in (-270, -180, -90, 90, 180, 270):

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="degrees_invalid")



    paths = batch_dir(str(document.batch_id))

    raw_file = paths.raw / document.filename

    if not raw_file.exists():

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="raw_missing")

    if not _is_pdf_document(document, raw_file):

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf_required")



    try:

        _rotate_pdf(raw_file, degrees)

    except Exception as exc:

        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="rotate_failed") from exc



    try:

        batch_service._generate_pdf_preview(raw_file, paths.preview_for(str(document.id)))

    except Exception:

        pass



    document.updated_at = datetime.utcnow()

    await session.flush()

    await session.commit()



    cache_bust = int(time.time())

    preview_url = f"/files/batches/{document.batch_id}/preview/{document.id}/page_1.png?v={cache_bust}"

    return {

        "status": "ok",

        "message": "rotated",

        "doc_id": str(document.id),

        "degrees": degrees,

        "preview_url": preview_url,

    }




@router.post("/api/documents/{doc_id}/delete")

async def delete_document(

    doc_id: uuid.UUID,

    session: AsyncSession = Depends(get_db),

) -> Dict[str, Any]:

    document = await _load_document(session, doc_id)

    if document is None:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")


    _ensure_prep_open(document.batch)


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



    return {

        "status": "ok",

        "message": "document_deleted",

        "batch_id": str(batch_id),

        "doc_id": str(doc_id),

    }





@router.get("/batches/{batch_id}/report.xlsx")

async def download_batch_report(batch_id: uuid.UUID) -> StreamingResponse:

    try:

        buffer = await asyncio.to_thread(reports.export_report_excel_for_batch, batch_id)

    except FileNotFoundError:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report_not_found")

    headers = {"Content-Disposition": f'attachment; filename="batch-{batch_id}-report.xlsx"'}

    return StreamingResponse(

        buffer,

        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

        headers=headers,

    )







def _prep_complete(batch: Any) -> bool:
    meta = batch.meta if isinstance(batch.meta, dict) else {}
    if "prep_complete" in meta:
        return bool(meta.get("prep_complete"))
    return batch.status not in (BatchStatus.NEW, BatchStatus.PREPARED)


def _ensure_prep_open(batch: Any) -> None:
    if _prep_complete(batch):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="prep_locked")


def _is_pdf_document(document: Document, path: Path) -> bool:
    if document.mime:
        return document.mime.split(";", 1)[0].strip().lower() == "application/pdf"
    return path.suffix.lower() == ".pdf"


def _rotate_pdf(path: Path, degrees: int) -> None:
    if degrees % 90 != 0:
        raise ValueError("degrees must be multiple of 90")
    doc = fitz.open(path)  # type: ignore[misc]
    try:
        for page in doc:
            page.set_rotation((page.rotation + degrees) % 360)
        temp_path = path.with_suffix(path.suffix + ".rotated")
        doc.save(temp_path)
        temp_path.replace(path)
    finally:
        doc.close()


async def _load_document(session: AsyncSession, doc_id: uuid.UUID) -> Optional[Document]:

    stmt = (

        select(Document)

        .where(Document.id == doc_id)

        .options(selectinload(Document.fields), selectinload(Document.batch))

    )

    result = await session.execute(stmt)

    return result.scalar_one_or_none()





def _build_field_states(document: Document) -> Tuple[List[Dict[str, Any]], int]:

    fields: List[Dict[str, Any]] = []

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

        source: Optional[FilledField],

    ) -> None:

        nonlocal pending

        needs_confirmation = reason in {"missing", "low_confidence"}

        if needs_confirmation:

            pending += 1

        bbox = None

        page = None

        token_refs: Optional[List[str]] = None

        if source is not None:

            bbox = list(source.bbox) if isinstance(source.bbox, list) else source.bbox

            page = int(source.page) if source.page is not None else None

            if source.token_refs is not None:

                token_refs = list(source.token_refs)

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

                "bbox": bbox,

                "page": page,

                "token_refs": token_refs,

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

            source=None,

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

                    source=field,

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

                    source=field,

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

                    source=field,

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

                source=field,

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

                source=field,

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

                source=field,

            )

    # Filter out any stored fields not present in the current schema
    latest_fields = {k: v for k, v in latest_fields.items() if k in schema.fields}
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

            source=field,

        )



    return fields, pending





def _build_product_comparisons(report_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:

    if not report_payload:

        return []

    return list(report_payload.get("product_comparisons", []))





def _build_product_comparison_matrix(

    product_comparisons: List[Dict[str, Any]],

) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:

    return [], []





def _format_doc_type_label(key: str) -> str:

    return key





def _build_product_table(document: Document) -> Dict[str, Any]:

    schema = get_schema(document.doc_type)

    products_schema = schema.fields.get("products") if schema else None

    template = None

    if products_schema and products_schema.children:

        template = products_schema.children.get("product_template")



    if template is None or not template.children:

        return {"columns": [], "rows": []}



    columns: List[Dict[str, str]] = []

    column_keys: List[str] = []

    for key, field_schema in template.children.items():

        columns.append({"key": key, "label": field_schema.label or key})

        column_keys.append(key)



    rows: List[Dict[str, Any]] = []

    latest_fields: Dict[str, FilledField] = {

        field.field_key: field for field in document.fields if field.latest

    }

    base_key = "products"



    for index in range(0, 500):

        row_key = f"{base_key}.{index}"

        row_cells: Dict[str, Any] = {}

        has_values = False



        for column_key in column_keys:

            field_key = f"{row_key}.{column_key}"

            field = latest_fields.get(field_key)

            value = field.value if field else None

            confidence = float(field.confidence) if field and field.confidence is not None else None

            if value not in (None, ""):

                has_values = True

            row_cells[column_key] = {

                "value": value,

                "confidence": confidence,

                "confidence_display": f"{confidence:.2f}" if confidence is not None else None,

            }



        if not has_values:

            break



        rows.append({"key": row_key, "cells": row_cells})



    return {"columns": columns, "rows": rows}





def _format_validation_detail(

    ref: Dict[str, Any],

    doc_info: Optional[Dict[str, str]],

) -> Optional[str]:

    label = ref.get("label")

    field_key = ref.get("field_key")

    page = ref.get("page")

    parts: List[str] = []

    if label:

        parts.append(str(label))

    if doc_info:

        filename = doc_info.get("filename")

        if filename:

            parts.append(filename)

    if page is not None:

        parts.append(f"page {page}")

    if field_key:

        parts.append(str(field_key))

    detail = " В· ".join(parts) if parts else None

    return detail if detail else None





def _build_validation_matrix(

    report_payload: Optional[Dict[str, Any]],

    documents_payload: List[Dict[str, Any]],

) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:

    if not report_payload:

        return [], []



    validations = report_payload.get("validations") or []

    if not validations:

        return [], []



    doc_info: Dict[str, Dict[str, str]] = {}

    for doc in documents_payload:

        doc_id = str(doc.get("id")) if doc.get("id") is not None else None

        if doc_id:

            doc_info[doc_id] = {

                "doc_type": doc.get("doc_type"),

                "filename": doc.get("filename"),

            }



    for doc in report_payload.get("documents", []):

        doc_id = doc.get("doc_id")

        if doc_id is None:

            continue

        key = str(doc_id)

        info = doc_info.get(key, {}).copy()

        if doc.get("doc_type"):

            info["doc_type"] = doc.get("doc_type")

        if doc.get("filename"):

            info["filename"] = doc.get("filename")

        doc_info[key] = info



    doc_types_present: set[str] = set()

    for info in doc_info.values():

        doc_type = info.get("doc_type")

        if doc_type:

            doc_types_present.add(doc_type)



    for item in validations:

        for ref in item.get("refs", []):

            ref_doc_type = ref.get("doc_type")

            if ref_doc_type:

                doc_types_present.add(ref_doc_type)

            doc_id = ref.get("doc_id")

            if doc_id is not None:

                info = doc_info.get(str(doc_id))

                if info and info.get("doc_type"):

                    doc_types_present.add(info["doc_type"])



    columns: List[Dict[str, str]] = []

    used_keys: set[str] = set()

    for doc_type in DocumentType:

        key = doc_type.value

        if key in doc_types_present:

            columns.append({"key": key, "label": _format_doc_type_label(key)})

            used_keys.add(key)

    for key in sorted(doc_types_present):

        if key not in used_keys:

            columns.append({"key": key, "label": _format_doc_type_label(key)})

            used_keys.add(key)



    rows: List[Dict[str, Any]] = []

    for item in validations:

        cells_map: Dict[str, List[str]] = {col["key"]: [] for col in columns}

        for ref in item.get("refs", []):

            doc_id = ref.get("doc_id")

            info = doc_info.get(str(doc_id)) if doc_id is not None else None

            doc_type = info.get("doc_type") if info and info.get("doc_type") else ref.get("doc_type")

            if not doc_type:

                continue

            if doc_type not in cells_map:

                cells_map[doc_type] = []

            detail = _format_validation_detail(ref, info)

            if detail:

                cells_map[doc_type].append(detail)



        rows.append(

            {

                "rule_id": item.get("rule_id"),

                "severity": item.get("severity"),

                "message": item.get("message"),

                "cells": {key: "\n".join(values) if values else None for key, values in cells_map.items()},

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

