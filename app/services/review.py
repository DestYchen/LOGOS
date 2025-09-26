from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentType
from app.core.schema import get_schema
from app.models import Batch, Document, FilledField


@dataclass
class ReviewFieldData:
    doc_id: uuid.UUID
    document_filename: str
    field_key: str
    value: Optional[str]
    confidence: float
    required: bool
    source: str
    page: Optional[int]
    bbox: Optional[List[float]]
    token_refs: Optional[List[str]]
    doc_type: DocumentType


def collect_review_data(batch: Batch, threshold: float) -> List[ReviewFieldData]:
    data: List[ReviewFieldData] = []
    for document in batch.documents:
        latest_fields: Dict[str, FilledField] = {
            field.field_key: field
            for field in document.fields
            if field.latest
        }
        schema = get_schema(document.doc_type)
        for key, field_schema in schema.fields.items():
            field = latest_fields.get(key)
            data.append(
                ReviewFieldData(
                    doc_id=document.id,
                    document_filename=document.filename,
                    field_key=key,
                    value=None if field is None else field.value,
                    confidence=0.0 if field is None else field.confidence,
                    required=field_schema.required,
                    source="missing" if field is None else field.source,
                    page=None if field is None else field.page,
                    bbox=None if field is None else field.bbox,
                    token_refs=None if field is None else field.token_refs,
                    doc_type=document.doc_type,
                )
            )
        for key, field in latest_fields.items():
            if key in schema.fields:
                continue
            data.append(
                ReviewFieldData(
                    doc_id=document.id,
                    document_filename=document.filename,
                    field_key=key,
                    value=field.value,
                    confidence=field.confidence,
                    required=False,
                    source=field.source,
                    page=field.page,
                    bbox=field.bbox,
                    token_refs=field.token_refs,
                    doc_type=document.doc_type,
                )
            )
    data.sort(key=lambda item: item.confidence)
    return data


async def upsert_field(
    session: AsyncSession,
    doc_id: uuid.UUID,
    field_key: str,
    value: Optional[str],
    bbox: Optional[List[float]],
    token_refs: Optional[List[str]],
    edited_by: Optional[str],
) -> FilledField:
    stmt = (
        select(Document)
        .where(Document.id == doc_id)
        .options(selectinload(Document.fields), selectinload(Document.batch))
    )
    result = await session.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        raise ValueError("document_not_found")

    previous_latest = None
    for field in document.fields:
        if field.field_key == field_key and field.latest:
            field.latest = False
            previous_latest = field

    latest_version = max((field.version for field in document.fields if field.field_key == field_key), default=0)
    new_field = FilledField(
        doc_id=document.id,
        field_key=field_key,
        value=value,
        page=previous_latest.page if previous_latest else None,
        bbox=bbox if bbox is not None else (previous_latest.bbox if previous_latest else None),
        token_refs=token_refs if token_refs is not None else (previous_latest.token_refs if previous_latest else None),
        confidence=1.0,
        source="user",
        version=latest_version + 1,
        latest=True,
        edited_by=edited_by,
        edited_at=datetime.utcnow(),
    )
    session.add(new_field)

    await session.flush()
    return new_field


def review_ready(batch: Batch, threshold: float) -> bool:
    for document in batch.documents:
        if document.doc_type == DocumentType.UNKNOWN:
            return False
        schema = get_schema(document.doc_type)
        latest_fields: Dict[str, FilledField] = {
            field.field_key: field
            for field in document.fields
            if field.latest
        }
        for key, field_schema in schema.fields.items():
            field = latest_fields.get(key)
            if field_schema.required and (field is None or field.value is None):
                return False
            if field is not None and field.confidence < threshold:
                return False
    return True
