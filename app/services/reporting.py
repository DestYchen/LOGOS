from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import BatchStatus
from app.core.storage import batch_dir
from app.models import Batch, Document, FilledField, Validation


async def load_batch_with_fields(session: AsyncSession, batch_id: uuid.UUID) -> Batch:
    stmt = (
        select(Batch)
        .where(Batch.id == batch_id)
        .options(selectinload(Batch.documents).selectinload(Document.fields))
    )
    result = await session.execute(stmt)
    batch = result.scalar_one()
    return batch


async def fetch_validations(session: AsyncSession, batch_id: uuid.UUID) -> List[Validation]:
    stmt = select(Validation).where(Validation.batch_id == batch_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def generate_report(session: AsyncSession, batch_id: uuid.UUID) -> Dict[str, Any]:
    batch = await load_batch_with_fields(session, batch_id)
    validations = await fetch_validations(session, batch_id)

    documents_payload: List[Dict[str, Any]] = []
    for document in batch.documents:
        fields_payload = {
            field.field_key: {
                "value": field.value,
                "confidence": field.confidence,
                "source": field.source,
                "page": field.page,
                "bbox": field.bbox,
            }
            for field in document.fields
            if field.latest
        }
        documents_payload.append(
            {
                "doc_id": str(document.id),
                "filename": document.filename,
                "doc_type": document.doc_type.value,
                "status": document.status.value,
                "fields": fields_payload,
            }
        )

    validations_payload = [
        {
            "rule_id": validation.rule_id,
            "severity": validation.severity.value,
            "message": validation.message,
            "refs": validation.refs or [],
        }
        for validation in validations
    ]

    processing_warnings = (batch.meta or {}).get("processing_warnings", [])
    for index, warning in enumerate(processing_warnings, start=1):
        validations_payload.append(
            {
                "rule_id": f"processing_warning_{index}",
                "severity": "warn",
                "message": warning,
                "refs": [],
            }
        )

    payload = {
        "batch_id": str(batch.id),
        "status": batch.status.value,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "documents": documents_payload,
        "validations": validations_payload,
        "meta": batch.meta or {},
    }

    report_path = batch_dir(str(batch_id)).report
    report_path.mkdir(parents=True, exist_ok=True)
    output_file = report_path / "report.json"
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    if batch.status != BatchStatus.DONE:
        batch.status = BatchStatus.DONE

    return payload
